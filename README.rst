.. -*- mode: rst -*-

|Travis|_ |Codecov|_ |Python27|_ |Python35|_

.. |Travis| image:: https://travis-ci.com/CherkaouiHamza/pybold.svg?token=tt8GRtf9hkYvmyTMbYvJ&branch=master
.. _Travis: https://travis-ci.com/CherkaouiHamza/pybold

.. |Codecov| image:: https://codecov.io/gh/CherkaouiHamza/pybold/branch/master/graph/badge.svg
.. _Codecov: https://codecov.io/gh/CherkaouiHamza/pybold

.. |Python27| image:: https://img.shields.io/badge/python-2.7-blue.svg
.. _Python27: https://badge.fury.io/py/scikit-learn

.. |Python35| image:: https://img.shields.io/badge/python-3.5-blue.svg
.. _Python35: https://badge.fury.io/py/scikit-learn


pyBOLD
======

pyBOLD is a Python module for semi-blind deconvolution of the fMRI signal (BOLD).
This package reproduces the results of the `Cherkaoui et al., ICASSP 2019, paper <https://hal.archives-ouvertes.fr/hal-02085810>`_ :

 [1] Hamza Cherkaoui, Thomas Moreau, Abderrahim Halimi, Philippe Ciuciu,
 "Sparsity-based blind deconvolution of neural activation signal in fMRI",
 2019 IEEE International Conference on Acoustic Speech and Signal Processing, May 2019, Brighton, United Kingdom.

Important links
===============

- Official source code repo: https://github.com/CherkaouiHamza/pybold
- `Cherkaoui et al., ICASSP 2019, paper <https://hal.archives-ouvertes.fr/hal-02085810>`_

Dependencies
============

The required dependencies to use the software are:

* Numba
* Joblib
* Numpy
* Scipy
* PyWavelets
* Matplotlib (for examples)


License
=======
All material is Free Software: BSD license (3 clause).


Installation
============

In order to perform the installation, run the following command from the pybold directory::

    python setup.py install --user

To run all the tests, run the following command from the pybold directory::

    python -m unittest discover pybold/tests

To run the synthetic examples, go to the directories examples/synth_data and run a script, e.g.::

    python deconv.py

To reproduce the ICASSP 2019 plots, go to the directories examples/icassp_2019 and run the scripts, e.g.::

    python validation.py
    python simulation.py

Development
===========

Code
----

GIT
~~~

You can check the latest sources with the command::

    git clone git://github.com/CherkaouiHamza/pybold

or if you have write privileges::

    git clone git@github.com:CherkaouiHamza/pybold
