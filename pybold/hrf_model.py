# coding: utf-8
""" This module gathers usefull data generation.
"""
import numpy as np
from scipy.stats import gamma


MIN_DELTA = 0.5
MAX_DELTA = 2.0


def spm_hrf(delta, t_r=1.0, dur=60.0, normalized_hrf=True, dt=0.001, p_delay=6,
            undershoot=16.0, p_disp=1.0, u_disp=1.0, p_u_ratio=0.167,
            onset=0.0):
    """ SPM canonical HRF with a time scaling parameter.
    """
    if (delta < MIN_DELTA) or (delta > MAX_DELTA):
        raise ValueError("delta should belong in [{0}, {1}]; wich correspond"
                         " to a max FWHM of 10.52s and a min FWHM of 2.80s"
                         ", got delta = {2}".format(MIN_DELTA, MAX_DELTA,
                                                    delta))

    # dur: the (continious) time segment on which we represent all
    # the HRF. Can cut the HRF too early. The time scale is second.
    t = np.linspace(0, dur, int(float(dur) / dt)) - float(onset) / dt
    scaled_time_stamps = delta * t

    peak = gamma.pdf(scaled_time_stamps, p_delay/p_disp, loc=dt/p_disp)
    undershoot = gamma.pdf(scaled_time_stamps, undershoot/u_disp,
                           loc=dt/u_disp)
    hrf = peak - p_u_ratio * undershoot

    if normalized_hrf:
        hrf /= np.max(hrf + 1.0e-30)

    hrf = hrf[::int(t_r/dt)]
    t_hrf = t[::int(t_r/dt)]

    return hrf, t_hrf
