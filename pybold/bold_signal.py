# coding: utf-8
""" Main module that provide the blind deconvolution function.
"""
import numpy as np
from scipy.optimize import fmin_l_bfgs_b
import matplotlib.pyplot as plt
from .hrf_model import spm_hrf, MIN_DELTA, MAX_DELTA
from .linear import DiscretInteg, Conv, ConvAndLinear, Diff
from .gradient import SquaredL2ResidualLinear, L2ResidualLinear
from .solvers import nesterov_forward_backward
from .proximity import L1Norm
from .utils import Tracker, mad_daub_noise_est, inf_norm, fwhm, tp


def deconvolution(noisy_ar_s, tr, hrf, lbda=None, L2_res=False,
                  early_stopping=True, tol=1.0e-3, wind=2, nb_iter=1000,
                  verbose=0, ai_s=None):
    """ Deconvolve the given BOLD signal given an HRF convolution kernel.
    The source signal is supposed to be a bloc signal.

    Parameters:
    ----------
    noisy_ar_s : 1d np.ndarray,
        the observed bold signal.

    tr : float,
        the TR.

    hrf : 1d np.ndarray,
        the HRF.

    lbda : float (default=1.0),
        the regularization parameter.

    verbose : int (default=0),
        the verbosity level.

    Return:
    ------
    est_ar_s : 1d np.ndarray,
        the estimated convolved signal.

    est_ai_s : 1d np.ndarray,
        the estimated convolved signal.

    est_i_s : 1d np.ndarray,
        the estimated convolved signal.

    J : 1d np.ndarray,
        the evolution of the cost-function.
    """
    if wind < 2:
        raise ValueError("wind should at least 2, got {0}".format(wind))

    l_alpha, J, R, G = [], [], [], []
    N = len(noisy_ar_s)

    v0 = np.zeros(N)

    Integ = DiscretInteg()
    H = ConvAndLinear(Integ, hrf, dim_in=N, dim_out=N)
    if L2_res:
        grad = SquaredL2ResidualLinear(H, noisy_ar_s, v0.shape)
    else:
        grad = L2ResidualLinear(H, noisy_ar_s, v0.shape)

    if lbda is not None:
        # solve 0.5 * || L h conv alpha - y ||_2^2 + lbda * || alpha ||_1
        prox = L1Norm(lbda)
        x, J = nesterov_forward_backward(
                        grad=grad, prox=prox, v0=v0, nb_iter=nb_iter,
                        early_stopping=True, verbose=verbose,
                          )

        est_i_s = x
        est_ai_s = Integ.op(x)
        est_ar_s = Conv(hrf, N).op(est_ai_s)

        return est_ar_s, est_ai_s, est_i_s, J, None, None

    else:
        # solve || x ||_1 sc  || L h conv alpha - y ||_2^2 < sigma
        sigma = mad_daub_noise_est(noisy_ar_s)  # estim. of the noise std
        nb_iter = nb_iter  # nb iters for main loop
        alpha = 1.0  # init regularization parameter lbda = 1/(2*alpha)
        mu = 5.0e-3  # gradient step of the lbda optimization
        for i in range(nb_iter):
            # deconvolution step
            lbda = 1.0 / (2.0 * alpha)
            prox = L1Norm(lbda)
            x, _ = nesterov_forward_backward(
                            grad=grad, prox=prox, v0=v0, nb_iter=999,
                            early_stopping=True, verbose=verbose,
                              )
            # lambda optimization
            alpha += mu * (grad.residual(x) - N * sigma**2)

            # iterate update and saving
            l_alpha.append(alpha)
            if len(l_alpha) > wind:  # only hold the 'wind' last iterates
                l_alpha = l_alpha[1:]

            # metrics evolution
            r = grad.residual(x)
            g = np.sum(np.abs(x))
            R.append(r)
            G.append(g)
            lbda = 1.0 / (2.0 * alpha)
            J.append(0.5 * r + lbda * g)
            if verbose > 0:
                print("Main loop: iteration {0:03d},"
                      " lbda = {1:0.6f},"
                      " l1-norm = {2:0.6f},"
                      " N*sigma**2 = {3:0.6f},"
                      " res = {4:0.6f}".format(i+1, lbda, g,
                                                           N*sigma**2, r))

            # early stopping
            if early_stopping:
                if i > wind:
                    sub_wind_len = int(wind/2)
                    old_iter = np.mean(l_alpha[:-sub_wind_len], axis=0)
                    new_iter = np.mean(l_alpha[-sub_wind_len:], axis=0)
                    crit_num = np.abs(new_iter - old_iter)
                    crit_deno = np.abs(new_iter)
                    diff = crit_num / crit_deno
                    if diff < tol:
                        if verbose > 1:
                            print("\n-----> early-stopping "
                                  "done at {0:03d}/{1:03d}, "
                                  "cost function = {2:.6f}".format(i, nb_iter,
                                                                   J[i]))
                        break

        # last deconvolution with larger number of iterations
        lbda = 1.0 / (2.0 * alpha)
        prox = L1Norm(lbda)
        x, _ = nesterov_forward_backward(
                        grad=grad, prox=prox, v0=v0, nb_iter=9999,
                        early_stopping=True, verbose=verbose,
                          )

        est_i_s = x
        est_ai_s = Integ.op(x)
        est_ar_s = Conv(hrf, N).op(est_ai_s)

        return est_ar_s, est_ai_s, est_i_s, J, R, G


def hrf_fit_err(hrf_params, ai_i_s, ar_s, hrf_cst_params, hrf_func, L2_res):
    """ Cost function for the scaled-gamma HRF model.
    e.g. 0.5 * || h*x - y ||_2^2 with h an HRF model.
    """
    H = Conv(hrf_func(hrf_params, *hrf_cst_params)[0], len(ar_s))

    if L2_res:
        return 0.5 * np.linalg.norm(ar_s - H.op(ai_i_s))
    else:
        return 0.5 * np.sum(np.square(ar_s - H.op(ai_i_s)))


def scale_factor_hrf_estimation(ai_i_s, ar_s, tr=1.0, dur=60.0, verbose=0):
    """ HRF scaled Gamma function estimation.

    Parameters:
    -----------
    ai_i_s : 1d np.ndarray,
        the source signal.

    ar_s : 1d np.ndarray,
        the convolved signal.

    tr : float (default=1.0),
        the TR.

    dur : float (default=60.0),
        number of seconds on which represent the HRF.

    verbose : int (default=0)

    Return:
    ------
    hrf : 1d np.ndarray,
        the estimated HRF.

    J : 1d np.ndarray,
        the evolution of the cost-function.
    """
    return _hrf_estimation(ai_i_s, ar_s, params_init=1.0,
                           hrf_cst_params=[tr, dur], hrf_func=spm_hrf,
                           bounds=[(MIN_DELTA + 1.0e-1, MAX_DELTA - 1.0e-1)],
                           L2_res=True, verbose=verbose)


def _hrf_estimation(ai_i_s, ar_s, params_init, hrf_cst_params, hrf_func,
                    bounds, L2_res=True, verbose=0):
    """ Private function HRF estimation.
    """
    args = (ai_i_s, ar_s, hrf_cst_params, hrf_func, L2_res)
    args = tuple(args)
    f_cost = Tracker(hrf_fit_err, args, verbose)

    hrf_params, f_value, _ = fmin_l_bfgs_b(
                        func=hrf_fit_err, x0=params_init, args=args,
                        bounds=bounds, approx_grad=True, callback=f_cost)
    J = f_cost.J

    hrf = hrf_func(hrf_params, *hrf_cst_params)[0]

    return hrf, J


def blind_blocs_deconvolution( # noqa
                        noisy_ar_s, tr, lbda_bold=1.0, hrf_func=None,
                        hrf_params=None, hrf_cst_params=None, bounds=None,
                        init_i_s=None, dur_hrf=60.0, L2_res=True, nb_iter=50,
                        early_stopping=False, wind=24, tol=1.0e-24, verbose=0,
                        plotting=False, ai_s=None, hrf=None):
    """ BOLD blind deconvolution function based on a scaled HRF model and an
    blocs BOLD model.
    """
    # initialization of the HRF
    if (hrf_params is None) and (hrf_func is None) and \
       (hrf_cst_params is None):
        hrf_params = 1.0
        hrf_cst_params = [tr, dur_hrf]
        hrf_func = spm_hrf
        bounds = [(MIN_DELTA + 1.0e-1, MAX_DELTA - 1.0e-1)]
    elif (hrf_params is None) or (hrf_func is None) or \
         (hrf_cst_params is None):
        raise ValueError("Please specify properly the HRF model")

    est_hrf_params = hrf_params
    est_hrf = hrf_func(est_hrf_params, *hrf_cst_params)[0]

    N = len(noisy_ar_s)
    # definition of the usefull operator
    Integ = DiscretInteg()
    prox_bold = L1Norm(lbda_bold)

    # initialization of the source signal
    if init_i_s is None:
        est_i_s = np.zeros(N)  # init spiky signal
        est_ai_s = np.zeros(N)  # init spiky signal
        est_ar_s = np.zeros(N)  # thus.. init convolved signal
    else:
        est_i_s = init_i_s
        est_ai_s = Integ.op(est_i_s)
        est_ar_s = Conv(est_hrf, N).op(est_ai_s)

    # init cost function value
    J = []
    r = np.sum(np.square(est_ar_s - noisy_ar_s))
    g_bold = np.sum(np.abs(est_i_s))
    J.append(0.5 * r + lbda_bold * g_bold)

    if (verbose > 0):
        print("global cost-function "
              "({0:03d}/{1:03d}): {2:.6f}".format(0, nb_iter, J[-1]))
    if plotting:
        fig = plt.figure(np.random.randint(99999), figsize=(20, 8))
        plt.ion()

    for idx in range(nb_iter):

        if plotting:

            t_hrf = np.linspace(0, dur_hrf, int(dur_hrf/tr))
            noisy_ar_s, est_ar_s = inf_norm([noisy_ar_s, est_ar_s])
            est_ai_s, est_i_s, est_hrf = inf_norm([est_ai_s, est_i_s, est_hrf])

            if (ai_s is not None) and (hrf is not None):
                i_s = Diff().op(ai_s)
                ai_s, i_s, hrf = inf_norm([ai_s, i_s, hrf])

            plt.gcf().clear()

            t = np.linspace(0, int(N * float(tr)), N)

            ax0 = fig.add_subplot(3, 1, 1)
            ax0.plot(t, noisy_ar_s, label="observed signal", lw=0.5)
            ax0.plot(t, est_ar_s, label="denoised signal", lw=1.0)
            ax0.set_yticklabels([])
            ax0.set_xlabel("time (s)")
            ax0.set_ylabel("ampl.")
            ax0.set_yticklabels([])
            plt.legend()
            plt.grid()
            title = "Convolved signals ({0:03d}/{1:03d})".format(idx+1, nb_iter)
            ax0.set_title(title, fontsize=15)

            ax1 = fig.add_subplot(3, 1, 2)
            ax1.plot(t, est_ai_s, label="bloc signal", lw=1.5)
            ax1.stem(t, est_i_s, label="spike signal")
            if (ai_s is not None) and (hrf is not None):
                ax1.plot(t, ai_s, label="orig. bloc signal", lw=1.5)
                ax1.stem(t, i_s, label="orig. spike signal")
            ax1.set_yticklabels([])
            ax1.set_xlabel("time (s)")
            ax1.set_ylabel("ampl.")
            ax1.set_yticklabels([])
            plt.legend()
            plt.grid()
            title = "Source signals ({0:03d}/{1:03d})".format(idx+1, nb_iter)
            ax1.set_title(title, fontsize=15)

            ax2 = fig.add_subplot(3, 1, 3)
            label = ("est. HRF, params='{0}' FWHM={1:.2f}s, "
                     "TP={2:.2f}s".format(est_hrf_params, fwhm(t_hrf, est_hrf),
                                          tp(t_hrf, est_hrf)))
            ax2.plot(t_hrf, est_hrf, label=label, lw=1.0)
            if (ai_s is not None) and (hrf is not None):

                label = ("orig. HRF, FWHM={0:.2f}s, "
                         "TP={1:.2f}s".format(fwhm(t_hrf, hrf),
                                              tp(t_hrf, hrf)))
                ax2.plot(t_hrf, hrf, label=label, lw=1.0)
            ax2.set_yticklabels([])
            ax2.set_xlabel("time (s)")
            ax2.set_ylabel("ampl.")
            ax2.set_yticklabels([])
            plt.legend()
            plt.grid()
            title = "est. HRF ({0:03d}/{1:03d})".format(idx+1, nb_iter)
            ax2.set_title(title, fontsize=15)

            plt.tight_layout()

            plt.pause(0.1)

        # BOLD deconvolution
        H = ConvAndLinear(Integ, est_hrf, dim_in=N, dim_out=N)

        v0 = est_i_s
        if L2_res:
            grad = SquaredL2ResidualLinear(H, noisy_ar_s, v0.shape)
        else:
            grad = L2ResidualLinear(H, noisy_ar_s, v0.shape)
        est_i_s, _ = nesterov_forward_backward(
                    grad=grad, prox=prox_bold, v0=v0, nb_iter=50000,
                    early_stopping=True, wind=2, tol=1.0e-10, verbose=verbose,
                        )

        est_ai_s = Integ.op(est_i_s)
        est_ar_s = Conv(est_hrf, N).op(est_ai_s)

        # HRF estimation
        args = [est_ai_s, noisy_ar_s] + [hrf_cst_params] + [hrf_func] + [True]
        args = tuple(args)
        est_hrf_params, f_value, _ = fmin_l_bfgs_b(
                            func=hrf_fit_err, x0=est_hrf_params, args=args,
                            bounds=bounds, approx_grad=True)
        est_hrf = hrf_func(est_hrf_params, *hrf_cst_params)[0]
        est_ar_s = Conv(est_hrf, N).op(est_ai_s)

        # cost function
        r = np.sum(np.square(est_ar_s - noisy_ar_s))
        g_bold = np.sum(np.abs(est_i_s))
        J.append(0.5 * r + lbda_bold * g_bold)

        if (verbose > 0):
            print("global cost-function "
                  "({0:03d}/{1:03d}): {2:.6f}".format(idx+1, nb_iter, J[-1]))

        # early stopping
        if early_stopping:
            if idx > wind:
                sub_wind_len = int(wind/2)
                old_j = np.mean(J[:-sub_wind_len])
                new_j = np.mean(J[-sub_wind_len:])
                diff = (new_j - old_j) / new_j
                if diff < tol:
                    if verbose > 0:
                        print("\n-----> early-stopping done at "
                              "{0:03d}/{1:03d}, global"
                              " cost-function = {2:.6f}".format(idx, nb_iter,
                                                                J[idx]))
                    break
    if plotting:
        plt.ioff()

    # last BOLD deconvolution
    H = ConvAndLinear(Integ, est_hrf, dim_in=N, dim_out=N)

    v0 = np.zeros(N)
    if L2_res:
        grad = SquaredL2ResidualLinear(H, noisy_ar_s, v0.shape)
    else:
        grad = L2ResidualLinear(H, noisy_ar_s, v0.shape)
    est_i_s, _ = nesterov_forward_backward(
                grad=grad, prox=prox_bold, v0=v0, nb_iter=100000,
                early_stopping=True, wind=8, tol=1.0e-24, verbose=verbose,
                    )

    est_ai_s = Integ.op(est_i_s)
    est_ar_s = Conv(est_hrf, N).op(est_ai_s)

    r = np.sum(np.square(est_ar_s - noisy_ar_s))
    g_bold = np.sum(np.abs(est_i_s))
    J.append(0.5 * r + lbda_bold * g_bold)

    J = np.array(J)

    return est_ar_s, est_ai_s, est_i_s, est_hrf, J


def scaled_hrf_blind_blocs_deconvolution_auto_lbda( # noqa
                        noisy_ar_s, tr, hrf_func=None, hrf_params=None,
                        hrf_cst_params=None, init_i_s=None,
                        sigma=None, dur_hrf=60.0, nb_iter=50,
                        L2_res=True,
                        early_stopping=False, wind=24, tol=1.0e-24,
                        verbose=0, plotting=False):
    """ BOLD blind deconvolution function based on a scaled HRF model and an
    blocs BOLD model.
    """
    bounds = None
    # initialization of the HRF
    if (hrf_params is None) and (hrf_func is None) and \
       (hrf_cst_params is None):
        est_hrf_params = 1.0
        hrf_cst_params = [tr, dur_hrf]
        hrf_func = spm_hrf
        bounds = [(MIN_DELTA + 1.0e-1, MAX_DELTA - 1.0e-1)]
    elif (hrf_params is None) or (hrf_func is None) or \
         (hrf_cst_params is None):
        raise ValueError("Please specify properly the HRF model")

    est_hrf_params = hrf_params
    est_hrf = hrf_func(est_hrf_params, *hrf_cst_params)[0]

    N = len(noisy_ar_s)
    # definition of the usefull operator
    Integ = DiscretInteg()

    sigma = mad_daub_noise_est(noisy_ar_s) if sigma is None else sigma
    nb_iter_deconv = 50  # nb iters for main loop
    alpha = 1.0  # init regularization parameter lbda = 1/(2*alpha)
    lbda = 1.0 / (2.0 * alpha)
    mu = 1.0e-2  # gradient step of the lbda optimization

    # initialization of the source signal
    if init_i_s is None:
        est_i_s = np.zeros(N)  # init spiky signal
        est_ai_s = np.zeros(N)  # init spiky signal
        est_ar_s = np.zeros(N)  # thus.. init convolved signal
    else:
        est_i_s = init_i_s
        est_ai_s = Integ.op(est_i_s)
        est_ar_s = Conv(est_hrf, N).op(est_ai_s)

    # init cost function value
    J, l_alpha = [], []
    r = np.sum(np.square(est_ar_s - noisy_ar_s))
    J.append(0.5 * r + lbda * np.sum(np.abs(est_i_s)))

    if (verbose > 0):
        print("global cost-function "
              "({0:03d}/{1:03d}): {2:.6f}".format(0, nb_iter, J[-1]))
    if plotting:
        fig = plt.figure(np.random.randint(99999), figsize=(20, 20))
        plt.ion()

    for i in range(nb_iter):

        # BOLD DECONVOLUTION --------------------------------

        H = ConvAndLinear(Integ, est_hrf, dim_in=N, dim_out=N)
        v0 = est_i_s
        if L2_res:
            grad = SquaredL2ResidualLinear(H, noisy_ar_s, v0.shape)
        else:
            grad = L2ResidualLinear(H, noisy_ar_s, v0.shape)

        for j in range(nb_iter_deconv):
            # deconvolution step
            lbda = 1.0 / (2.0 * alpha)
            prox = L1Norm(lbda)
            x, _ = nesterov_forward_backward(
                            grad=grad, prox=prox, v0=v0, nb_iter=999,
                            early_stopping=True, verbose=verbose,
                              )
            # lambda optimization
            alpha += mu * (grad.residual(x) - N * sigma**2)

            # iterate update and saving
            l_alpha.append(alpha)
            if len(l_alpha) > wind:  # only hold the 'wind' last iterates
                l_alpha = l_alpha[1:]

            # early stopping
            if early_stopping:
                if j > 2:
                    sub_wind_len = int(wind/2)
                    old_iter = np.mean(l_alpha[:-sub_wind_len], axis=0)
                    new_iter = np.mean(l_alpha[-sub_wind_len:], axis=0)
                    crit_num = np.abs(new_iter - old_iter)
                    crit_deno = np.abs(new_iter)
                    diff = crit_num / (crit_deno + 1.0e-10)
                    if diff < 1.0e-2:
                        if verbose > 1:
                            print("\n-----> early-stopping "
                                  "done at {0:03d}/{1:03d}, "
                                  "cost function = {2:.6f}".format(j+1,
                                                                   nb_iter,
                                                                   J[j]))
                        break

        # deconvolution with larger number of iterations
        prox = L1Norm(1.0 / (2.0 * alpha))
        est_i_s, _ = nesterov_forward_backward(
                        grad=grad, prox=prox, v0=v0, nb_iter=9999,
                        early_stopping=True, verbose=verbose,
                          )

        est_ai_s = Integ.op(est_i_s)

        # HRF ESTIMATION --------------------------------

        args = [est_ai_s, noisy_ar_s] + [hrf_cst_params] + [hrf_func] + [True]
        args = tuple(args)
        est_hrf_params, f_value, _ = fmin_l_bfgs_b(
                            func=hrf_fit_err, x0=est_hrf_params, args=args,
                            bounds=bounds, approx_grad=True)
        est_hrf = hrf_func(est_hrf_params, *hrf_cst_params)[0]
        est_ar_s = Conv(est_hrf, N).op(est_ai_s)

        if plotting:

            t_hrf = np.linspace(0, dur_hrf, int(dur_hrf/tr))
            max_hrf, _ = spm_hrf(MIN_DELTA, tr=tr, dur=dur_hrf)
            min_hrf, _ = spm_hrf(MAX_DELTA, tr=tr, dur=dur_hrf)
            max_hrf, min_hrf, nest_hrf = inf_norm([max_hrf, min_hrf, est_hrf])

            plt.gcf().clear()

            t = np.linspace(0, int(N * float(tr)), N)
            ax0 = fig.add_subplot(2, 1, 1)
            ax0.plot(t, noisy_ar_s, label="observed signal", lw=0.5)
            ax0.plot(t, est_ar_s, label="denoised signal", lw=1.0)
            ax0.plot(t, est_ai_s, label="bloc signal", lw=1.5)
            ax0.stem(t, est_i_s, label="spike signal")
            ax0.set_yticklabels([])
            ax0.set_xlabel("time (s)")
            ax0.set_ylabel("ampl.")
            ax0.set_yticklabels([])
            plt.legend()
            plt.grid()
            ax0.set_title("Signal", fontsize=12)

            ax1 = fig.add_subplot(2, 1, 2)
            ax1.plot(t_hrf, nest_hrf, label="est. HRF", lw=1.0)
            ax1.plot(t_hrf, min_hrf, '--k', label="min. HRF", lw=1.5)
            ax1.plot(t_hrf, max_hrf, '--k', label="max. HRF", lw=1.5)
            ax1.set_yticklabels([])
            ax1.set_xlabel("time (s)")
            ax1.set_ylabel("ampl.")
            ax1.set_yticklabels([])
            plt.legend()
            plt.grid()
            ax1.set_title("est. HRF", fontsize=12)

            fig.suptitle('Evo. estimation '
                         '({0:03d}/{1:03d})'.format(i+1, nb_iter), fontsize=18)

            plt.tight_layout()

            plt.pause(0.1)

        # cost function
        r = np.sum(np.square(est_ar_s - noisy_ar_s))
        J.append(0.5 * r + lbda * np.sum(np.abs(est_i_s)))

        if (verbose > 0):
            print("global cost-function "
                  "({0:03d}/{1:03d}): {2:.6f}".format(i+1, nb_iter, J[-1]))

        # early stopping
        if early_stopping:
            if i > wind:
                sub_wind_len = int(wind/2)
                old_j = np.mean(J[:-sub_wind_len])
                new_j = np.mean(J[-sub_wind_len:])
                diff = (new_j - old_j) / (new_j + 1.0e-10)
                if diff < tol:
                    if verbose > 0:
                        print("\n-----> early-stopping done at "
                              "{0:03d}/{1:03d}, global cost-function"
                              " = {2:.6f}".format(i, nb_iter, J[i]))
                    break
    if plotting:
        plt.ioff()

    # last BOLD deconvolution
    H = ConvAndLinear(Integ, est_hrf, dim_in=N, dim_out=N)
    v0 = np.zeros(N)
    if L2_res:
        grad = SquaredL2ResidualLinear(H, noisy_ar_s, v0.shape)
    else:
        grad = L2ResidualLinear(H, noisy_ar_s, v0.shape)

    for j in range(nb_iter_deconv):
        # deconvolution step
        lbda = 1.0 / (2.0 * alpha)
        prox = L1Norm(lbda)
        x, _ = nesterov_forward_backward(
                        grad=grad, prox=prox, v0=v0, nb_iter=999,
                        early_stopping=True, verbose=verbose,
                          )
        # lambda optimization
        alpha += mu * (grad.residual(x) - N * sigma**2)

        # iterate update and saving
        l_alpha.append(alpha)
        if len(l_alpha) > wind:  # only hold the 'wind' last iterates
            l_alpha = l_alpha[1:]

        # early stopping
        if early_stopping:
            if j > 2:
                sub_wind_len = int(wind/2)
                old_iter = np.mean(l_alpha[:-sub_wind_len], axis=0)
                new_iter = np.mean(l_alpha[-sub_wind_len:], axis=0)
                crit_num = np.abs(new_iter - old_iter)
                crit_deno = np.abs(new_iter)
                diff = crit_num / (crit_deno + 1.0e-10)
                if diff < 1.0e-2:
                    if verbose > 1:
                        print("\n-----> early-stopping "
                              "done at {0:03d}/{1:03d}, "
                              "cost function = {2:.6f}".format(j+1,
                                                               nb_iter,
                                                               J[j]))
                    break

    # deconvolution with larger number of iterations
    prox = L1Norm(1.0 / (2.0 * alpha))
    est_i_s, _ = nesterov_forward_backward(
                    grad=grad, prox=prox, v0=v0, nb_iter=9999,
                    early_stopping=True, verbose=verbose,
                      )

    est_ai_s = Integ.op(est_i_s)

    r = np.sum(np.square(est_ar_s - noisy_ar_s))
    g_bold = np.sum(np.abs(est_i_s))
    J.append(0.5 * r + lbda * g_bold)

    J = np.array(J)

    return est_ar_s, est_ai_s, est_i_s, est_hrf, J
