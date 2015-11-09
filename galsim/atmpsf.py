# Copyright (c) 2012-2015 by the GalSim developers team on GitHub
# https://github.com/GalSim-developers
#
# This file is part of GalSim: The modular galaxy image simulation toolkit.
# https://github.com/GalSim-developers/GalSim
#
# GalSim is free software: redistribution and use in source and binary forms,
# with or without modification, are permitted provided that the following
# conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions, and the disclaimer given in the accompanying LICENSE
#    file.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions, and the disclaimer given in the documentation
#    and/or other materials provided with the distribution.
#
"""@file atmpsf.py
Module for generating atmospheric PSFs using an autoregressive phase screen generator.

Relevant SPIE paper:
"Remembrance of phases past: An autoregressive method for generating realistic atmospheres in
simulations"
Srikar Srinath, Univ. of California, Santa Cruz;
Lisa A. Poyneer, Lawrence Livermore National Lab.;
Alexander R. Rudy, UCSC; S. Mark Ammons, LLNL
Published in Proceedings Volume 9148: Adaptive Optics Systems IV
September 2014

"""

import numpy as np
import galsim
import utilities
from galsim import GSObject


class AtmosphericPhaseGenerator(object):
    """ Create an autoregressive atmospheric turbulence phase generator.

    @param time_step in seconds [Default: 0.03]
    @param screen_size in meters [Default: 10]
    @param screen_scale in meters [Default: 0.1]
    @param r0 in meters [Default: 0.2]
    @param velocity in meters/second [Default: 0]
    @param direction CCW relative to +x as galsim.Angle [Default: 0*galsim.degrees]
    @param alpha_mag [Default: 0.999]
    @param rng BaseDeviate instance to provide random number generation

    The implicit atmosphere model here is that turbulence is confined to a set of 2D phase screens
    at different altitudes. The number of atmosphere layers is determined from the length of the
    `r0`, `velocity`, or `direction` arguments, if they are lists. If these arguments have different
    lengths then select the length of the longest input to define the number of layers.

    Some suggestions for choices of wind velocities come from data hosted by NOAA. The Global Data
    Assimilation System (GDAS), run by the NOAA National Center for Environmental Prediction (NCEP),
    puts out various datasets. GDAS produces analyses every six hours, giving a large number of
    parameters tabulated at 24 altitudes in the atmosphere covering the entire Earth. The following
    is an example of wind velocities extracted from a file for 2014, Feb 13, 6h UT at the longitude
    and latitude of CTIO. (Wind velocities are m/s). Altitudes are approximate.
        Altitude (km)    velocity (m/s)    direction (deg.)
            1               0.98                -66
            10              0.67                116
            30              18.0                 27
    Data is found here: ftp://arlftp.arlhq.noaa.gov/pub/archives/gdas1/
    Data documentation: http://ready.arl.noaa.gov/gdas1.php
    """
    def __init__(self, time_step=0.03, screen_size=10.0, screen_scale=0.1,
                 r0=0.2, velocity=0.0, direction=0*galsim.degrees, alpha_mag=0.999,
                 rng=None):
        if rng is None:
            rng = galsim.BaseDeviate()
        self.rng = rng

        npix = int(np.ceil(screen_size/screen_scale))
        self.screen_size = screen_scale * npix  # in case screen_scale doesn't divide screen_size

        # Listify
        r0, velocity, direction, alpha_mag = map(
            lambda i: [i] if not hasattr(i, '__iter__') else i,
            (r0, velocity, direction, alpha_mag)
        )

        # Broadcast
        n_layers = max(map(len, [r0, velocity, direction, alpha_mag]))
        if n_layers > 1:
            r0, velocity, direction, alpha_mag = map(
                lambda i: [i[0]]*n_layers if len(i) == 1 else i,
                (r0, velocity, direction, alpha_mag)
            )

        if any(len(i) != n_layers for i in (r0, velocity, direction, alpha_mag)):
            raise ValueError("r0, velocity, direction, alpha_mag not broadcastable")

        # decompose velocities
        vx, vy = zip(*[v*d.sincos() for v, d in zip(velocity, direction)])

        # setup frequency grid
        fx = np.fft.fftfreq(npix, screen_scale)
        fx, fy = np.meshgrid(fx, fx)

        # setup phase screens states
        self.powerlaw = np.empty((n_layers, npix, npix), dtype=np.float64)
        self.alpha = np.empty((n_layers, npix, npix), dtype=np.complex128)
        self._phaseFT = np.empty((n_layers, npix, npix), dtype=np.complex128)
        self.screens = np.zeros_like(self.powerlaw)

        for i, (r00, vx0, vy0, amag0) in enumerate(zip(r0, vx, vy, alpha_mag)):
            pl = (1./self.screen_size*np.sqrt(0.00058)*(r00**(-5.0/6.0)) *
                  (fx*fx + fy*fy)**(-11.0/12.0) *
                  npix * np.sqrt(np.sqrt(2.0)))
            pl[0, 0] = 0.0
            self.powerlaw[i] = pl
            self._phaseFT[i] = self._noiseFT(pl)
            self.screens[i] = np.fft.ifft2(self._phaseFT[i]).real

            # make array for the alpha parameter and populate it
            alpha_phase = -(fx*vx0 + fy*vy0) * time_step
            self.alpha[i] = amag0 * np.exp(2j*np.pi*alpha_phase)

    def _noiseFT(self, powerlaw):
        gd = galsim.GaussianDeviate(self.rng)
        noise = utilities.rand_arr(powerlaw.shape, gd)
        return np.fft.fft2(noise)*powerlaw

    def next(self):
        for i, (pl, phFT, alpha) in enumerate(zip(self.powerlaw, self._phaseFT, self.alpha)):
            noisescalefac = np.sqrt(1. - np.abs(alpha**2))
            self._phaseFT[i] = alpha*phFT + self._noiseFT(pl)*noisescalefac
            self.screens[i] = np.fft.ifft2(self._phaseFT[i]).real
        return self.screens

    def __iter__(self):
        return self

    def __next__(self):
        return self.next()


class AtmosphericPSF(GSObject):
    """ Create an atmosphere PSF by summing over a phase cube in time steps.
    @param lam              Lambda (wavelength) in units of nanometers.  Must be supplied with `r0`,
                            and in this case, image scales (`scale`) should be specified in units of
                            `scale_unit`.
    @param r0               Fried parameter (in meters) setting the amplitude of turbulence due to
                            all layers.  [Default: 0.2]
    @param lam_over_r0      Lambda / Fried parameter
    @param fwhm             Full width at half max (FWHM) of the PSF in the infinite exposure limit
                            in arcseconds. [Default: 0.8]
    @param weights          Relative weights for each turbulent layer in terms of the layers'
                            refractive index fluctuations C_n^2.  The Fried parameter for each layer
                            is then set via r0_i = r_0 * weight_i^(-3/5).
    @param alpha_mag        Magnitude of autoregressive parameter.  (1-alpha) is the fraction of the
                            phase from the prior time step that is "forgotten" and replaced by
                            Gaussian noise.  [Default: 0.999]
    @param exptime          Exposure time in seconds. [Default: 0]
    @param time_step        Interval between PSF images in seconds. [Default: 0.03]
    @param velocity         Velocity magnitude of each phase screen layer in meters / second.
                            [Default: 0]
    @param direction        CCW relative to +x as galsim.Angle.  [Default: 0*galsim.degrees]
    @param phase_generator  AtmosphericPhaseGenerator object.  [Default: None]
    @param interpolant      Either an Interpolant instance or a string indicating which interpolant
                            should be used.  Options are 'nearest', 'sinc', 'linear', 'cubic',
                            'quintic', or 'lanczosN' where N should be the integer order to use.
                            [Default: galsim.Quintic()]
    @param oversampling     Optional oversampling factor for the InterpolatedImage. Setting
                            `oversampling < 1` will produce aliasing in the PSF (not good).
                            Usually `oversampling` should be somewhat larger than 1.  1.5 is
                            usually a safe choice.  [Default: 1.5]
    @param flux             Total flux of the profile. [Default: 1.]
    @param scale_unit       Units used to define the diffraction limit and draw images, if the user
                            has supplied a separate value for `lam` and `r0`.  Should be either a
                            galsim.AngleUnit, or a string that can be used to construct one (e.g.,
                            'arcsec', 'radians', etc.).
                            [Default: galsim.arcsec]
    @param gsparams         An optional GSParams argument.  See the docstring for GSParams for
                            details. [Default: None]
    """
    def __init__(self, lam=None, r0=None, lam_over_r0=None, fwhm=None, weights=None,
                 alpha_mag=None, exptime=0.0, time_step=0.03, velocity=0.0,
                 direction=0*galsim.degrees, phase_generator=None, interpolant=None,
                 oversampling=1.5, flux=1.0, scale_unit=galsim.arcsec, gsparams=None):
        import itertools

        nstep = int(np.ceil(exptime/time_step))
        if nstep == 0:
            nstep = 1

        if alpha_mag is None:
            alpha_mag = 0.999

        if phase_generator is not None:
            if any(item is not None for item in (lam, r0, lam_over_r0, fwhm, weights, alpha_mag)):
                raise ValueError("Cannot specify lam, r0, lam_over_r0, fwhm, weights, or alpha_mag"
                                 " when specifying phase_generator")
        else:
            # First determine the size (effective r0) of the requested PSF.
            if fwhm is not None:
                lam_over_r0 = fwhm / 0.975865
            if weights is not None:
                if r0 is not None:
                    if hasattr(r0, '__len__'):
                        raise ValueError("Cannot specify both weights and list of r0s.")
                    r0 = [r0 * w**(-3./5) for w in weights]
                elif lam_over_r0 is not None:
                    if hasattr(lam_over_r0, '__len__'):
                        raise ValueError("Cannot specify both weights and list of lam_over_r0s.")
                    lam_over_r0 = [lam_over_r0 * w**(3./5) for w in weights]
            # Listify
            r0, velocity, direction, alpha_mag, lam_over_r0 = map(
                lambda i: [i] if not hasattr(i, '__iter__') else i,
                (r0, velocity, direction, alpha_mag, lam_over_r0)
            )

            if lam is None:
                lam = 800.  # arbitrarily set wavelength = 800nm
                r0 = [lam*1.e-9 / lor0 * galsim.radians / scale_unit for lor0 in lam_over_r0]
            # Should have lam, {r0} at this point.
            r0_effective = (sum(r**(-5./3) for r in r0)**(-3./5))

            print "r0_effective: ", r0_effective
            print "lam_over_r0:", lam_over_r0
            print "r0: ", r0
            print "lam: ", lam
            print "alpha_mag: ", alpha_mag
            print "velocity: ", velocity
            print "direction: ", direction

            # Sampling the phase screen is roughly analogous to sampling the PSF in Fourier space.
            # We can use a Kolmogorov profile to get a rough estimate of what stepK is needed to
            # avoid aliasing.
            kolm = galsim.Kolmogorov(lam=lam, r0=r0_effective)
            screen_scale = kolm.stepK()/(2*np.pi)  # 2pi b/c np and GalSim FFT conventions differ.
            # an arbitrary additional factor of 4 to account for the fact that a stochastic
            # atmospheric PSF can have significant fluctuations at relatively large radii.
            screen_scale /= 4
            # We'll hard code screen_size = 10 meters since that covers all planned ground-based
            # weak lensing experiments.
            screen_size = 10.
            phase_generator = AtmosphericPhaseGenerator(
                time_step=time_step, screen_size=screen_size, screen_scale=screen_scale, r0=r0,
                alpha_mag=alpha_mag, velocity=velocity, direction=direction)
        self.phase_generator = phase_generator

        scale = 1.e-9*lam/self.phase_generator.screen_size * galsim.radians / scale_unit
        # Generate PSFs for each time step
        nx, ny = phase_generator.screens[0].shape
        im_grid = np.zeros((nx, ny), dtype=np.float64)
        for i, screens in itertools.izip(xrange(nstep), phase_generator):
            # The wavefront to use is exp(2 pi i screen)
            wf = np.exp(2j * np.pi * np.sum(screens, axis=0))
            # Calculate the image array via FFT.
            # Copied from galsim.optics.psf method (hacky)
            ftwf = np.fft.ifft2(np.fft.ifftshift(wf))
            im = np.abs(ftwf)**2
            # Add this PSF instance to stack to get the finite-exposure PSF
            im_grid += im

        im_grid = np.fft.fftshift(im_grid)
        im_grid *= (flux / (im_grid.sum() * scale**2))
        out_im = galsim.InterpolatedImage(
            galsim.Image(im_grid.astype(np.float64), scale=scale),
            x_interpolant=interpolant, calculate_stepk=True, calculate_maxk=True,
            use_true_center=False, normalization='sb')
        GSObject.__init__(self, out_im)