# Copyright 2012, 2013 The GalSim developers:
# https://github.com/GalSim-developers
#
# This file is part of GalSim: The modular galaxy image simulation toolkit.
#
# GalSim is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# GalSim is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with GalSim.  If not, see <http://www.gnu.org/licenses/>
#
"""@file sed.py
Simple spectral energy distribution class.  Used by galsim/chromatic.py
"""

import copy

import numpy

import galsim

class SED(object):
    """Simple SED object.

    SEDs are callable, returning the flux in photons/nm as a function of wavelength in nm.

    SEDs are immutable; all transformative SED methods return *new* SEDs, and leave their
    originating SEDs unaltered.

    SEDs have `blue_limit` and `red_limit` attributes, which may be set to `None` in the case that
    the SED is defined by a python function or lambda `eval` string.  SEDs are considered undefined
    outside of this range, and __call__ will raise an exception if a flux is requested outside of
    this range.

    SEDs may be multiplied by scalars or scalar functions of wavelength.

    SEDs may be added together.  The resulting SED will only be defined on the wavelength
    region where both of the operand SEDs are defined. `blue_limit` and `red_limit` will be reset
    accordingly.
    """
    def __init__(self, spec, flux_type='flambda'):
        """Simple SED object.  This object is callable, returning the flux in
        photons/nm as a function of wavelength in nm.

        The input parameter, spec, may be one of several possible forms:
        1. a regular python function (or an object that acts like a function)
        2. a galsim.LookupTable
        3. a file from which a LookupTable can be read in
        4. a string which can be evaluated into a function of `wave`
           via `eval('lambda wave : '+spec)
           e.g. spec = '0.8 + 0.2 * (wave-800)`

        The argument of the function will be the wavelength in nanometers, and the output should be
        the dimensionless throughput at that wavelength.  (Note we use wave rather than lambda,
        since lambda is a python reserved word.)

        The argument `flux_type` specifies the type of spectral density and must be one of:
        1. 'flambda':  `spec` is proportional to erg/nm
        2. 'fnu':      `spec` is proportional to erg/Hz
        3. 'fphotons': `spec` is proportional to photons/nm

        @param spec          Function defining the spectrum at each wavelength.  See above for
                             valid options for this parameter.
        @param flux_type     String specifying what type of spectral density `spec` represents.  See
                             above for valid options for this parameter.
        """
        if isinstance(spec, (str, unicode)):
            import os
            if os.path.isfile(spec):
                spec = galsim.LookupTable(file=spec)
            else:
                spec = eval('lambda wave : ' + spec)

        if isinstance(spec, galsim.LookupTable):
            self.blue_limit = spec.x_min
            self.red_limit = spec.x_max
        else:
            self.blue_limit = None
            self.red_limit = None

        if flux_type == 'flambda':
            self.fphotons = lambda w: spec(w) * w
        elif flux_type == 'fnu':
            self.fphotons = lambda w: spec(w) / w
        elif flux_type == 'fphotons':
            self.fphotons = spec
        else:
            raise ValueError("Unknown flux_type `{}` in SED.__init__".format(flux_type))

        self.redshift = 0.0

    def _wavelength_intersection(self, other):
        blue_limit = None
        if self.blue_limit is not None:
            blue_limit = self.blue_limit
        if other.blue_limit is not None and blue_limit is not None:
            blue_limit = max([blue_limit, other.blue_limit])
        red_limit = None
        if self.red_limit is not None:
            red_limit = self.red_limit
        if other.red_limit is not None and red_limit is not None:
            red_limit = min([red_limit, other.red_limit])
        return blue_limit, red_limit

    def __call__(self, wave):
        """ Return photon density at wavelength `wave`.

        Note that outside of the wavelength range defined by the `blue_limit` and `red_limit`
        attributes, the SED is considered undefined, and this method will raise an exception if a
        flux at a wavelength outside the defined range is requested.

        @param   wave  Wavelength at which to evaluate the SED.
        @returns       Photon density, Units proportional to photons/nm
        """
        if hasattr(wave, '__iter__'): # Only iterables respond to min(), max()
            wmin = min(wave)
            wmax = max(wave)
        else: # python scalar
            wmin = wave
            wmax = wave
        if self.blue_limit is not None:
            if wmin < self.blue_limit:
                raise ValueError("Wavelength ({}) is bluer than SED blue limit ({})"
                                 .format(wmin, self.blue_lim))
        if self.red_limit is not None:
            if wmax > self.red_limit:
                raise ValueError("Wavelength ({}) redder than SED red limit ({})"
                                 .format(wmax, self.red_limit))
        return self.fphotons(wave)

    def __mul__(self, other):
        # SEDs can be multiplied by scalars or functions (callables)
        ret = self.copy()
        if hasattr(other, '__call__'):
            ret.fphotons = lambda w: self.fphotons(w) * other(w)
        else:
            ret.fphotons = lambda w: self.fphotons(w) * other
        return ret

    def __rmul__(self, other):
        return self*other

    def __div__(self, other):
        # SEDs can be divided by scalars or functions (callables)
        ret = self.copy()
        if hasattr(other, '__call__'):
            ret.fphotons = lambda w: self.fphotons(w) / other(w)
        else:
            ret.fphotons = lambda w: self.fphotons(w) / other
        return ret

    def __rdiv__(self, other):
        # SEDs can be divided by scalars or functions (callables)
        ret = self.copy()
        if hasattr(other, '__call__'):
            ret.fphotons = lambda w: other(w) / self.fphotons(w)
        else:
            ret.fphotons = lambda w: other / self.fphotons(w)
        return ret

    def __truediv__(self, other):
        return self.__div__(other)

    def __rtruediv__(self, other):
        return self.__rdiv__(other)

    def __add__(self, other):
        # Add together two SEDs, with caveats listed below:
        #
        # 1) The resulting SED will be defined on the wavelength range set by the overlap of
        #    the (possibly redshifted!) wavelength ranges of the two SED operands.
        # 2) The redshift of the resulting SED will be set to 0.0 regardless of the redshifts of the
        #    SED operands.
        # These ensure that SED addition is commutative.

        # Find overlapping wavelength interval
        blue_limit, red_limit = self._wavelength_intersection(other)
        ret = self.copy()
        ret.blue_limit = blue_limit
        ret.red_limit = red_limit
        ret.fphotons = lambda w: self(w) + other(w)
        ret.redshift = 0.0
        return ret

    def __sub__(self, other):
        # Subtract two SEDs, with caveats listed below:
        #
        # 1) The resulting SED will be defined on the wavelength range set by the overlap of
        #    the (possibly redshifted!) wavelength ranges of the two SED operands.
        # 2) The redshift of the resulting SED will be set to 0.0 regardless of the redshifts of the
        #    SED operands.
        # These ensure that SED subtraction is anticommutative.

        # Find overlapping wavelength interval
        return self.__add__(-1.0 * other)

    def copy(self):
        cls = self.__class__
        ret = cls.__new__(cls)
        for k, v in self.__dict__.iteritems():
            ret.__dict__[k] = copy.deepcopy(v) # need deepcopy for copying self.fphotons
        return ret

    def setNormalization(self, base_wavelength, normalization):
        """ Set photon density normalization at specified wavelength.  Note that this
        normalization is *relative* to the flux of the chromaticized GSObject.

        @param base_wavelength    The wavelength, in nanometers, at which the normalization will
                                  be set.
        @param normalization      The target *relative* normalization in photons / nm.
        """
        current_fphotons = self(base_wavelength)
        norm = normalization / current_fphotons
        ret = self.copy()
        ret.fphotons = lambda w: self.fphotons(w) * norm
        return ret

    def setFlux(self, bandpass, flux_norm):
        """ Set flux of SED when observed through given bandpass.  Note that the final number
        of counts drawn into an image is a function of both the SED and the chromaticized
        GSObject's flux attribute.

        @param bandpass   A galsim.Bandpass object defining a filter bandpass.
        @param flux_norm  Desired *relative* flux contribution from the SED.
        """
        current_flux = self.getFlux(bandpass)
        norm = flux_norm/current_flux
        ret = self.copy()
        ret.fphotons = lambda w: self.fphotons(w) * norm
        return ret

    def setRedshift(self, redshift):
        """ Scale the wavelength axis of the SED.

        @param redshift
        """
        ret = self.copy()
        wave_factor = (1.0 + redshift) / (1.0 + self.redshift)
        ret.fphotons = lambda w: self.fphotons(w / wave_factor)
        ret.redshift = redshift
        ret.blue_limit = self.blue_limit * wave_factor
        ret.red_limit = self.red_limit * wave_factor
        return ret

    def getFlux(self, bandpass):
        """ Return the SED flux through a bandpass.

        @param bandpass   galsim.Bandpass object representing a filter, or None for bolometric
                          flux (over defined wavelengths).
        @returns   Flux through bandpass.
        """
        if bandpass is None:
            if self.blue_limit is None:
                blue_limit = 0.0
            else:
                blue_limit = self.blue_limit
            if self.red_limit is None:
                red_limit = 1.e11 # = infinity in int1d
            else:
                red_limit = self.red_limit
            return galsim.integ.int1d(self.fphotons, blue_limit, red_limit)
        else:
            return galsim.integ.int1d(lambda w: bandpass(w)*self.fphotons(w),
                                      bandpass.blue_limit, bandpass.red_limit)
