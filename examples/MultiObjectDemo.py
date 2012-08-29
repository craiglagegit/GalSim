#!/usr/bin/env python
"""
Some example scripts to make multi-object images using the GalSim library.
"""

import sys
import os
import subprocess
import math
import numpy
import logging
import time

# This machinery lets us run Python examples even though they aren't positioned
# properly to find galsim as a package in the current directory.
try:
    import galsim
except ImportError:
    path, filename = os.path.split(__file__)
    sys.path.append(os.path.abspath(os.path.join(path, "..")))
    import galsim

# Script 1: Make multiple galaxy images, reading in many of the relevant parameters
# from an input catalog.
def Script1():
    """
    Make a fits image cube using parameters from an input catalog
      - The number of images in the cube matches the number of rows in the catalog.
      - Each image size is computed automatically by GalSim based on the Nyquist size.
      - Only galaxies.  No stars.
      - PSF is Moffat
      - Each galaxy is bulge plus disk: deVaucouleurs + Exponential.
      - Parameters taken from the input catalog:
        - PSF beta
        - PSF FWHM
        - PSF e1
        - PSF e2
        - PSF trunc
        - Bulge half-light-radius
        - Bulge e1
        - Bulge e2
        - Bulge flux
        - Disc half-light-radius
        - Disc e1
        - Disc e2
        - Disc flux
        - Galaxy dx (two components have same center)
        - Galaxy dy
      - Applied shear is the same for each file
      - Noise is poisson using a nominal sky value of 1.e6
    """
    logger = logging.getLogger("Script1")

    # Define some parameters we'll use below.

    cat_file_name = os.path.join('input','galsim_default_input.asc')
    multi_file_name = os.path.join('output','multi.fits')
    cube_file_name = os.path.join('output','cube.fits')

    random_seed = 8241573
    sky_level = 1.e6                # ADU / arcsec^2
    pixel_scale = 1.0               # arcsec / pixel  (size units in input catalog are pixels)
    gal_flux = 1.e6                 # arbitrary choise, makes nice (not too) noisy images
    gal_g1 = -0.009                 #
    gal_g2 = 0.011                  #
    xsize = 64                      # pixels
    ysize = 64                      # pixels

    logger.info('Starting multi-object script 2 using:')
    logger.info('    - parameters taken from catalog %r',cat_file_name)
    logger.info('    - Moffat PSF (parameters from catalog)')
    logger.info('    - pixel scale = %.2f',pixel_scale)
    logger.info('    - Bulge + Disc galaxies (parameters from catalog)')
    logger.info('    - Applied gravitational shear = (%.3f,%.3f)',gal_g1,gal_g2)
    logger.info('    - Poisson noise (sky level = %.1e).', sky_level)

    # Setup the config object
    config = galsim.Config()

    # The configuration should set up several top level things:
    # config.psf defines the PSF
    # config.pix defines the pixel response
    # config.gal defines the galaxy
    # They are all currently required, although eventually we will probably make it so
    # they are each optional.

    # Each type of profile is specified by a type.  e.g. Moffat:
    config.psf.type = 'Moffat'

    # The various parameters are typically specified as well
    config.psf.beta = 3.5

    # These parameters do not need to be constant.  There are a number of ways to
    # specify variables that might change from object to object.
    # In this case, the parameter specification also has a "type".
    # For now we only have InputCatalog, which means read the value from a catalog:
    config.psf.fwhm.type = 'InputCatalog'

    # InputCatalog requires the extra value of which column to use in the catalog:
    # Note: the first column is called 0, not 1, as per the usual python 
    # 0-based indexing scheme.
    config.psf.fwhm.col = 5

    # You can also specify both of these on the same line as a single string:
    config.psf.trunc = 'InputCatalog col=8'

    # You can even nest string values using angle brackets:
    config.psf.ellip = 'E1E2 e1=<InputCatalog col=6> e2=<InputCatalog col=7>'

    # If you don't specify a parameter, and there is a reasonable default, then it 
    # will be used instead.  If there is no reasonable default, you will get an error.
    #config.psf.flux = 1  # Unnecessary

    # If you want to use a variable in your string, you can use Python's % notation:
    config.pix = 'SquarePixel size=%f'%pixel_scale

    # A profile can be the sum of several components, each with its own type and parameters:
    config.gal.type = 'Sum'
    # TODO: [galsim.Config()]*2 doesn't work, since shallow copies.
    # I guess we need a nicer way to initialize this.
    config.gal.items = [galsim.Config(), galsim.Config()]
    config.gal.items[0].type = 'Exponential'
    config.gal.items[0].half_light_radius = 'InputCatalog col=9'
    config.gal.items[0].ellip = 'E1E2 e1=<InputCatalog col=10> e2=<InputCatalog col=11>'
    config.gal.items[0].flux = 0.6
    config.gal.items[1].type = 'DeVaucouleurs'
    config.gal.items[1].half_light_radius = 'InputCatalog col=12'
    config.gal.items[1].ellip = 'E1E2 e1=<InputCatalog col=13> e2=<InputCatalog col=14>'
    config.gal.items[1].flux = 0.4

    # When a composite object (like a Sum) has a flux specified, the "flux" values of the
    # components are taken to be relative fluxes, and the full object's value sets the
    # overall normalization.  If this is omitted, the overall flux is taken to be the
    # sum of the component fluxes.
    config.gal.flux = gal_flux

    # An object may have an ellip and a shear, each of which can be specified in terms
    # of either E1E2 (distortion) or G1G2 (reduced shear).
    # The only difference between the two is if there is also a rotation specified.
    # The order of the various modifications are:
    # - ellip
    # - rotation
    # - shear
    # - shift
    config.gal.shear = 'G1G2 g1=%f g2=%f'%(gal_g1,gal_g2)
    config.gal.shift = 'DXDY dx=<InputCatalog col=15> dy=<InputCatalog col=16>'


    # Read the catalog
    input_cat = galsim.io.ReadInputCat(config,cat_file_name)
    logger.info('Read %d objects from catalog',input_cat.nobjects)

    # Store these in config for use by the BuildGSObject functions.
    config.input_cat = input_cat

    # Build the images
    all_images = []
    for k in range(input_cat.nobjects):
        # Initialize the random number generator we will be using.
        # Note: This could be done once outside the loop.
        #       However, this is the initialization that our config parser uses in
        #       order to work when using multiple processes.
        #       Since we want these demo scripts to have identical output to the 
        #       versions using config files, we follow the same convention here.
        rng = galsim.UniformDeviate(random_seed+k)
        config.rng = rng

        t1 = time.time()
        #logger.info('Image %d',input_cat.current)

        psf = galsim.BuildGSObject(config,'psf')[0]
        #logger.info('   Made PSF profile')
        t2 = time.time()

        pix = galsim.BuildGSObject(config,'pix')[0]
        #logger.info('   Made pixel profile')
        t3 = time.time()

        gal = galsim.BuildGSObject(config,'gal')[0]
        #logger.info('   Made galaxy profile')
        t4 = time.time()

        final = galsim.Convolve([psf,pix,gal])
        #im = final.draw(dx=pixel_scale)  # It makes these as 768 x 768 images.  A bit big.
        im = galsim.ImageF(xsize, ysize)
        final.draw(im, dx=pixel_scale)
        #logger.info('   Drew image: size = %d x %d',xsize,ysize)
        t5 = time.time()

        # Add Poisson noise
        im += sky_level * pixel_scale**2
        im.addNoise(galsim.CCDNoise(rng))
        im -= sky_level * pixel_scale**2
        #logger.info('   Added noise')
        t6 = time.time()

        # Store that into the list of all images
        all_images += [im]
        t7 = time.time()

        #logger.info('   Times: %f, %f, %f, %f, %f, %f', t2-t1, t3-t2, t4-t3, t5-t4, t6-t5, t7-t6)
        logger.info('Image %d: size = %d x %d, total time = %f sec', k, xsize, ysize, t7-t1)

    logger.info('Done making images of galaxies')

    # Now write the image to disk.
    galsim.fits.writeMulti(all_images, multi_file_name, clobber=True)
    logger.info('Wrote images to multi-extension fits file %r',multi_file_name)

    galsim.fits.writeCube(all_images, cube_file_name, clobber=True)
    logger.info('Wrote image to fits data cube %r',cube_file_name)

    print

# Script 2: Something along the lines of a Great08 image
def Script2():
    """
    Make images similar to that done for the Great08 challenge:
      - Each fits file is 10 x 10 postage stamps.
        (The real Great08 images are 100x100, but in the interest of making the Demo
         script a bit quicker, we only build 100 stars and 100 galaxies.)
      - Each postage stamp is 40 x 40 pixels.
      - One image is all stars.
      - A second image is all galaxies.
      - Applied shear is the same for each galaxy.
      - Galaxies are oriented randomly, but in pairs to cancel shape noise.
      - Noise is poisson using a nominal sky value of 1.e6.
      - Galaxies are sersic profiles.
    """
    logger = logging.getLogger("Script2")

    # Define some parameters we'll use below.
    # Normally these would be read in from some parameter file.

    nx_stamps = 10                  #
    ny_stamps = 10                  #
    nx_pixels = 40                  #
    ny_pixels = 40                  #

    random_seed = 6424512           #

    pixel_scale = 1.0               # arcsec / pixel
    sky_level = 1.e6                # ADU / arcsec^2

    psf_file_name = os.path.join('output','g08_psf.fits')
    psf_beta = 3                    #
    psf_fwhm = 2.85                 # arcsec (=pixels)
    psf_trunc = 2.*psf_fwhm         # arcsec (=pixels)
    psf_e1 = -0.019                 #
    psf_e2 = -0.007                 #

    gal_file_name = os.path.join('output','g08_gal.fits')
    gal_signal_to_noise = 200       # Great08 "LowNoise" run
    gal_n = 1                       # Use n=1 for "disk" type
    # Great08 mixed pure bulge and pure disk for its LowNoise run.
    # We're just doing disks to make things simpler.
    gal_resolution = 0.98           # r_gal / r_psf (use r = half_light_radius)
                                    # This corresponds to a resolute = 1.4 in the Great08
                                    # definition of r_obs / r_psf
    gal_ellip_rms = 0.2             # using "shear" definition of ellipticity.
    gal_ellip_max = 0.6             #
    gal_g1 = 0.013                  #
    gal_g2 = -0.008                 #

    centroid_shift = 1.0            # arcsec (=pixels)

    logger.info('Starting multi-object script 1 using:')
    logger.info('    - image with %d x %d postage stamps',nx_stamps,ny_stamps)
    logger.info('    - postage stamps of size %d x %d pixels',nx_pixels,ny_pixels)
    logger.info('    - Moffat PSF (beta = %.1f, FWHM = %.2f, trunc = %.2f),',
            psf_beta,psf_fwhm,psf_trunc)
    logger.info('    - PSF ellip = (%.3f,%.3f)',psf_e1,psf_e2)
    logger.info('    - Sersic galaxies (n = %.1f)',gal_n)
    logger.info('    - Resolution (r_gal / r_psf) = %.2f',gal_resolution)
    logger.info('    - Ellipticities have rms = %.1f, max = %.1f',
            gal_ellip_rms, gal_ellip_max)
    logger.info('    - Applied gravitational shear = (%.3f,%.3f)',gal_g1,gal_g2)
    logger.info('    - Poisson noise (sky level = %.1e).', sky_level)
    logger.info('    - Centroid shifts up to = %.2f pixels',centroid_shift)


    # Define the PSF profile
    psf = galsim.Moffat(beta=psf_beta, flux=1., fwhm=psf_fwhm, trunc=psf_trunc)
    psf_re = psf.half_light_radius  # Need this for later...
    psf.applyShear(e1=psf_e1,e2=psf_e2)
    logger.info('Made PSF profile')

    pix = galsim.Pixel(xw=pixel_scale, yw=pixel_scale)
    logger.info('Made pixel profile')

    final_psf = galsim.Convolve([psf,pix])
    logger.info('Made final_psf profile')


    # Define the galaxy profile

    # First figure out the size we need from the resolution
    gal_re = psf_re * gal_resolution

    # Make the galaxy profile starting with flux = 1.
    gal = galsim.Sersic(gal_n, flux=1., half_light_radius=gal_re)
    logger.info('Made galaxy profile')

    # This profile is placed with different orientations and noise realizations
    # at each postage stamp in the gal image.
    gal_image = galsim.ImageF(nx_pixels * nx_stamps-1 , ny_pixels * ny_stamps-1)
    psf_image = galsim.ImageF(nx_pixels * nx_stamps-1 , ny_pixels * ny_stamps-1)

    centroid_shift_sq = centroid_shift**2

    first_in_pair = True  # Make pairs that are rotated by 45 degrees

    k = 0
    for ix in range(nx_stamps):
        for iy in range(ny_stamps):

            # Initialize the random number generator we will be using.
            rng = galsim.UniformDeviate(random_seed+k)
            gd = galsim.GaussianDeviate(rng, sigma=gal_ellip_rms)

            # The -1's in the next line are to provide a border of
            # 1 pixel between postage stamps
            b = galsim.BoundsI(ix*nx_pixels+1 , (ix+1)*nx_pixels-1, 
                               iy*ny_pixels+1 , (iy+1)*ny_pixels-1)
            sub_gal_image = gal_image[b]
            sub_psf_image = psf_image[b]

            # Great08 randomized the locations of the two galaxies in each pair,
            # but for simplicity, we just do them in sequential postage stamps.
            if first_in_pair:
                # Determine the ellipticity to use for this galaxy.
                ellip = 1
                while (ellip > gal_ellip_max):
                    # Don't do `ellip = math.fabs(gd())`
                    # Python basically implements this as a macro, so gd() is called twice!
                    val = gd()
                    ellip = math.fabs(val)

                # Apply a random orientation:
                beta = rng() * 2. * math.pi * galsim.radians
                first_in_pair = False
            else:
                beta += math.pi/2 * galsim.radians
                first_in_pair = True

            # Make a new copy of the galaxy with an applied e1/e2-type distortion 
            # by specifying the ellipticity and a real-space position angle
            this_gal = gal.createSheared(e=ellip, beta=beta)

            # Apply the gravitational reduced shear by specifying g1/g2
            this_gal.applyShear(g1=gal_g1, g2=gal_g2)

            # Apply a random centroid shift:
            rsq = 2 * centroid_shift_sq
            while (rsq > centroid_shift_sq):
                dx = (2*rng()-1) * centroid_shift
                dy = (2*rng()-1) * centroid_shift
                rsq = dx**2 + dy**2

            this_gal.applyShift(dx,dy)
            this_psf = final_psf.createShifted(dx,dy)

            # Make the final image, convolving with psf and pixel
            final_gal = galsim.Convolve([psf,pix,this_gal])

            # Draw the image
            final_gal.draw(sub_gal_image, dx=pixel_scale)

            # Now determine what we need to do to get our desired S/N
            # There are lots of definitions of S/N, but here is the one used by Great08
            # We use a weighted integral of the flux:
            # S = sum W(x,y) I(x,y) / sum W(x,y)
            # N^2 = Var(S) = sum W(x,y)^2 Var(I(x,y)) / (sum W(x,y))^2
            # Now we assume that Var(I(x,y)) is dominated by the sky noise, so
            # Var(I(x,y)) = sky_level
            # We also assume that we are using a matched filter for W, so W(x,y) = I(x,y).
            # Then a few things cancel and we find that
            # S/N = sqrt( sum I(x,y)^2 / sky_level )
            sky_level_pix = sky_level * pixel_scale**2
            sn_meas = math.sqrt( numpy.sum(sub_gal_image.array**2) / sky_level_pix )
            flux = gal_signal_to_noise / sn_meas
            # Now we rescale the flux to get our desired S/N
            sub_gal_image *= flux

            # Add Poisson noise
            sub_gal_image += sky_level_pix
            # The default CCDNoise has gain=1 and read_noise=0 if
            # these keyword args are not set, giving Poisson noise
            # according to the image pixel count values.
            sub_gal_image.addNoise(galsim.CCDNoise(rng))
            sub_gal_image -= sky_level_pix

            # Draw the PSF image
            # No noise on PSF images.  Just draw it as is.
            this_psf.draw(sub_psf_image, dx=pixel_scale)

            # for first instance, measure moments
            if ix==0 and iy==0:
                psf_shape = sub_psf_image.FindAdaptiveMom()
                g_to_e = psf_shape.observed_shape.getG() / psf_shape.observed_shape.getE()
                logger.info('Measured best-fit elliptical Gaussian for first PSF image: ')
                logger.info('  g1, g2, sigma = %7.4f, %7.4f, %7.4f (pixels)',
                            g_to_e*psf_shape.observed_shape.getE1(),
                            g_to_e*psf_shape.observed_shape.getE2(), psf_shape.moments_sigma)

            x = b.center().x
            y = b.center().y
            logger.info('Galaxy (%d,%d): center = (%.0f,%0.f)  (e,beta) = (%.4f,%.3f)',
                    ix,iy,x,y,ellip,beta/galsim.radians)
            k = k+1

    logger.info('Done making images of postage stamps')

    # Now write the images to disk.
    psf_image.write(psf_file_name, clobber=True)
    logger.info('Wrote PSF file %s',psf_file_name)

    gal_image.write(gal_file_name, clobber=True)
    logger.info('Wrote image to %r',gal_file_name)  # using %r adds quotes around filename for us

    print


# Script 3: Simulations with real galaxies from a catalog
def Script3():
    """
    Make a fits image cube using real COSMOS galaxies from a catalog describing the training
    sample.

      - The number of images in the cube matches the number of rows in the catalog.
      - Each image size is computed automatically by GalSim based on the Nyquist size.
      - Both galaxies and stars.
      - PSF is a double Gaussian, the same for each galaxy.
      - Galaxies are randomly rotated to remove the imprint of any lensing shears in the COSMOS
        data.
      - The same shear is applied to each galaxy.
      - Noise is poisson using a nominal sky value of 1.e6
        the noise in the original COSMOS data.
    """
    logger = logging.getLogger("Script3")

    # Define some parameters we'll use below.

    cat_file_name = os.path.join('data','real_galaxy_catalog_example.fits')
    image_dir = os.path.join('data')
    multi_file_name = os.path.join('output','multi_real.fits')
    cube_file_name = os.path.join('output','cube_real.fits')
    psf_file_name = os.path.join('output','psf_script3.fits')

    random_seed = 1512413
    sky_level = 1.e6        # ADU / arcsec^2
    pixel_scale = 0.15      # arcsec
    gal_flux = 1.e5         # arbitrary choice, makes nice (not too) noisy images
    gal_g1 = -0.027         #
    gal_g2 = 0.031          #
    psf_inner_fwhm = 0.6    # arcsec
    psf_outer_fwhm = 2.3    # arcsec
    psf_inner_fraction = 0.8  # fraction of total PSF flux in the inner Gaussian
    psf_outer_fraction = 0.2  # fraction of total PSF flux in the inner Gaussian
    ngal = 100  

    logger.info('Starting multi-object script 3 using:')
    logger.info('    - real galaxies from catalog %r',cat_file_name)
    logger.info('    - double Gaussian PSF')
    logger.info('    - pixel scale = %.2f',pixel_scale)
    logger.info('    - Applied gravitational shear = (%.3f,%.3f)',gal_g1,gal_g2)
    logger.info('    - Poisson noise (sky level = %.1e).', sky_level)
    
    # Read in galaxy catalog
    real_galaxy_catalog = galsim.RealGalaxyCatalog(cat_file_name, image_dir)
    real_galaxy_catalog.preload()
    logger.info('Read in %d real galaxies from catalog', real_galaxy_catalog.n)

    ## Make the ePSF
    # first make the double Gaussian PSF
    psf1 = galsim.Gaussian(fwhm = psf_inner_fwhm, flux = psf_inner_fraction)
    psf2 = galsim.Gaussian(fwhm = psf_outer_fwhm, flux = psf_outer_fraction)
    psf = psf1+psf2
    # make the pixel response
    pix = galsim.Pixel(xw = pixel_scale, yw = pixel_scale)
    # convolve PSF and pixel response function to get the effective PSF (ePSF)
    epsf = galsim.Convolve([psf, pix])
    # Draw this one with no noise.
    epsf_image = epsf.draw(dx = pixel_scale)
    # write to file
    epsf_image.write(psf_file_name, clobber = True)
    logger.info('Created ePSF and wrote to file %r',psf_file_name)

    # Build the images
    all_images = []
    for k in range(ngal):
        #logger.info('Start work on image %d',i)
        t1 = time.time()

        # Initialize the random number generator we will be using.
        rng = galsim.UniformDeviate(random_seed+k)

        gal = galsim.RealGalaxy(real_galaxy_catalog, index = k)
        #logger.info('   Read in training sample galaxy and PSF from file')
        t2 = time.time()

        # Set the flux
        gal.flux = gal_flux

        # Rotate by a random angle
        theta = 2.*math.pi * rng() * galsim.radians
        gal.applyRotation(theta)

        # Apply the desired shear
        gal.applyShear(g1=gal_g1, g2=gal_g2)
        
        # Make the combined profile
        final = galsim.Convolve([psf, pix, gal])

        # Draw the profile
        if k == 0:
            im = final.draw(dx=pixel_scale)
            xsize, ysize = im.array.shape
        else:
            im = galsim.ImageF(xsize,ysize)
            final.draw(im, dx=pixel_scale)

        #logger.info('   Drew image')
        t3 = time.time()

        # Add Poisson noise
        sky_level_pixel = sky_level * pixel_scale**2
        im += sky_level_pixel
        # Again, default is gain=1, read_noise=0
        # So this is just poisson noise with the current image flux values.
        im.addNoise(galsim.CCDNoise(rng)) 
        im -= sky_level_pixel

        #logger.info('   Added Poisson noise')
        t4 = time.time()

        # Store that into the list of all images
        all_images += [im]
        t5 = time.time()

        #logger.info('   Times: %f, %f, %f, %f',t2-t1, t3-t2, t4-t3, t5-t4)
        logger.info('Image %d: size = %d x %d, total time = %f sec', k, xsize, ysize, t5-t1)

    logger.info('Done making images of galaxies')

    # Now write the image to disk.
    galsim.fits.writeMulti(all_images, multi_file_name, clobber=True)
    logger.info('Wrote images to multi-extension fits file %r',multi_file_name)

    galsim.fits.writeCube(all_images, cube_file_name, clobber=True)
    logger.info('Wrote image to fits data cube %r',cube_file_name)

    print


# Script 4: Compare images of the same profile drawn using FFT convolution and photon shooting.
def Script4():
    """
    Make a fits image cube where each frame has two images of the same galaxy drawn 
    with regular FFT convolution and with photon shooting.

    We do this for 5 different PSFs and 5 different galaxies, each with 4 different (random)
    fluxes, sizes, and shapes.
    """
    logger = logging.getLogger("Script4")

    # Define some parameters we'll use below.

    file_name = os.path.join('output','cube_phot.fits')

    random_seed = 1512413
    sky_level = 1.e4        # ADU / arcsec^2
    pixel_scale = 0.28      # arcsec
    nx = 64
    ny = 64

    gal_flux_min = 1.e4     # Range for galaxy flux
    gal_flux_max = 1.e5  
    gal_hlr_min = 0.3       # arcsec
    gal_hlr_max = 1.3       # arcsec
    gal_e_min = 0.          # Range for ellipticity
    gal_e_max = 0.8

    psf_fwhm = 0.65         # arcsec

    logger.info('Starting multi-object script 4')

    # Make the pixel:
    pix = galsim.Pixel(xw = pixel_scale)

    # Make the PSF profiles:
    psf1 = galsim.Gaussian(fwhm = psf_fwhm)
    psf2 = galsim.Moffat(fwhm = psf_fwhm, beta = 2.4)
    psf3_inner = galsim.Gaussian(fwhm = psf_fwhm, flux = 0.8)
    psf3_outer = galsim.Gaussian(fwhm = 2*psf_fwhm, flux = 0.2)
    psf3 = psf3_inner + psf3_outer
    atmos = galsim.Gaussian(fwhm = psf_fwhm)
    optics = galsim.OpticalPSF(
            lam_over_D = 0.6 * psf_fwhm,
            obscuration = 0.4,
            defocus = 0.1,
            astig1 = 0.3, astig2 = -0.2,
            coma1 = 0.2, coma2 = 0.1,
            spher = -0.3) 
    psf4 = galsim.Convolve([atmos,optics])
    #atmos = galsim.AtmosphericPSF(fwhm = psf_fwhm)
    atmos = galsim.Kolmogorov(fwhm = psf_fwhm)
    optics = galsim.Airy(lam_over_D = 0.3 * psf_fwhm) 
    psf5 = galsim.Convolve([atmos,optics])
    psfs = [psf1, psf2, psf3, psf4, psf5]
    psf_names = ["Gaussian", "Moffat", "Double Gaussian", "OpticalPSF", "Kolmogorov * Airy"]
    psf_times = [0,0,0,0,0]
    psf_fft_times = [0,0,0,0,0]
    psf_phot_times = [0,0,0,0,0]

    # Make the galaxy profiles:
    gal1 = galsim.Gaussian(half_light_radius = 1)
    gal2 = galsim.Exponential(half_light_radius = 1)
    gal3 = galsim.DeVaucouleurs(half_light_radius = 1)
    gal4 = galsim.Sersic(half_light_radius = 1, n = 2.5)
    bulge = galsim.Sersic(half_light_radius = 0.7, n = 3.2)
    disk = galsim.Sersic(half_light_radius = 1.2, n = 1.5)
    gal5 = 0.4*bulge + 0.6*disk  # Net half-light radius is only approximate for this one.
    gals = [gal1, gal2, gal3, gal4, gal5]
    gal_names = ["Gaussian", "Exponential", "Devaucouleurs", "n=2.5 Sersic", "Bulge + Disk"]
    gal_times = [0,0,0,0,0]
    gal_fft_times = [0,0,0,0,0]
    gal_phot_times = [0,0,0,0,0]

    # Other times to keep track of:
    setup_times = 0
    fft_times = 0
    phot_times = 0
    noise_times = 0

    # Loop over combinations of psf, gal, and make 4 random choices for flux, size, shape.
    all_images = []
    k = 0
    for ipsf in range(len(psfs)):
        psf = psfs[ipsf]
        psf_name = psf_names[ipsf]
        for igal in range(len(gals)):
            gal = gals[igal]
            gal_name = gal_names[igal]
            for i in range(4):
                #logger.info('Start work on image %d',i)
                t1 = time.time()

                # Initialize the random number generator we will be using.
                rng = galsim.UniformDeviate(random_seed+k)

                # Generate random variates:
                flux = rng() * (gal_flux_max-gal_flux_min) + gal_flux_min
                hlr = rng() * (gal_hlr_max-gal_hlr_min) + gal_hlr_min
                ellip = rng() * (gal_e_max-gal_e_min) + gal_e_min
                beta_ellip = rng() * 2*math.pi * galsim.radians

                # Use create rather than apply for the first one to get a new copy.
                # Could also do gal1 = gal.copy() and then gal1.applyDilation(hlr)
                gal1 = gal.createDilated(hlr)
                gal_shape = galsim.Shear(e=ellip, beta=beta_ellip)
                gal1.applyShear(gal_shape)
                gal1.flux = flux

                # Build the final object by convolving the galaxy, PSF and pixel response.
                final = galsim.Convolve([psf, pix, gal1])
                # For photon shooting, need a version without the pixel (see below).
                final_nopix = galsim.Convolve([psf, gal1])

                # Create the large, double width output image
                image = galsim.ImageF(2*nx+2,ny)
                image.setScale(pixel_scale)
                # Then assign the following two "ImageViews", fft_image and phot_image.
                # Using the syntax below, these are views into the larger image.  
                # Changes/additions to the sub-images referenced by the views are automatically 
                # reflected in the original image.
                fft_image = image[galsim.BoundsI(1, nx, 1, ny)]
                phot_image = image[galsim.BoundsI(nx+3, 2*nx+2, 1, ny)]

                #logger.info('   Read in training sample galaxy and PSF from file')
                t2 = time.time()

                # Draw the profile
                final.draw(fft_image)

                #logger.info('   Drew fft image.  Total drawn flux = %f.  .flux = %f',
                        #fft_image.array.sum(),final.flux)
                t3 = time.time()

                # Repeat for photon shooting image.
                # Photon shooting automatically convolves by the pixel, so we've made sure not
                # to include it in the profile!
                sky_level_pixel = sky_level * pixel_scale**2
                final_nopix.drawShoot(phot_image, noise=sky_level_pixel/100, 
                                      uniform_deviate=rng)
                #logger.info('   Drew phot image.  Total drawn flux = %f.  .flux = %f',
                        #phot_image.array.sum(),final.flux)
                t4 = time.time()

                # Add Poisson noise
                fft_image += sky_level_pixel
                # Again, default is gain=1, read_noise=0
                # So this is just poisson noise with the current image flux values.
                fft_image.addNoise(galsim.CCDNoise(rng))
                fft_image -= sky_level_pixel

                # For photon shooting, galaxy already has poisson noise, so we want to make 
                # sure not to add that noise again!  Thus, we just add sky noise, which 
                # is Poisson with the mean = sky_level_pixel
                phot_image.addNoise(galsim.PoissonDeviate(rng, mean=sky_level_pixel))

                #logger.info('   Added Poisson noise.  Image fluxes are now %f and %f',
                        #fft_image.array.sum(),phot_image.array.sum())
                t5 = time.time()

                # Store that into the list of all images
                all_images += [image]

                k = k+1
                logger.info('%d: %s * %s, flux = %.2e, hlr = %.2f, ellip = (%.2f,%.2f)',
                        k,gal_name, psf_name, flux, hlr, gal_shape.getE1(), gal_shape.getE2())

                #logger.info('   Times: %f, %f, %f, %f',t2-t1, t3-t2, t4-t3, t5-t4)
                psf_times[ipsf] += t5-t1
                psf_fft_times[ipsf] += t3-t2
                psf_phot_times[ipsf] += t4-t3
                gal_times[igal] += t5-t1
                gal_fft_times[igal] += t3-t2
                gal_phot_times[igal] += t4-t3
                setup_times += t2-t1
                fft_times += t3-t2
                phot_times += t4-t3
                noise_times += t5-t4

    logger.info('Done making images of galaxies')
    logger.info('')
    logger.info('Some timing statistics:')
    logger.info('   Total time for setup steps = %f',setup_times)
    logger.info('   Total time for regular fft drawing = %f',fft_times)
    logger.info('   Total time for photon shooting = %f',phot_times)
    logger.info('   Total time for adding noise = %f',noise_times)
    logger.info('')
    logger.info('Breakdown by PSF type:')
    for ipsf in range(len(psfs)):
        logger.info('   %s: Total time = %f  (fft: %f, phot: %f)',
            psf_names[ipsf],psf_times[ipsf],psf_fft_times[ipsf],psf_phot_times[ipsf])
    logger.info('')
    logger.info('Breakdown by Galaxy type:')
    for igal in range(len(gals)):
        logger.info('   %s: Total time = %f  (fft: %f, phot: %f)',
            gal_names[igal],gal_times[igal],gal_fft_times[igal],gal_phot_times[igal])
    logger.info('')

    # Now write the image to disk.
    galsim.fits.writeCube(all_images, file_name, clobber=True)
    logger.info('Wrote fft image to fits data cube %r',file_name)

    print


# Script 5: Use multiple processes to draw image in parallel
def Script5():
    """
    Make an image containing 10 x 10 postage stamps.
    The galaxies are bulge + disk with parameters drawn from random variates
    Each galaxy is drawn using photon shooting.
    """
    from multiprocessing import Process, Queue, current_process, cpu_count

    logger = logging.getLogger("Script5")

    # Define some parameters we'll use below.

    single_file_name = os.path.join('output','bpd_single.fits')
    multi_file_name = os.path.join('output','bpd_multi.fits')

    random_seed = 1512413
    sky_level = 1.e4        # ADU / arcsec^2
    pixel_scale = 0.28      # arcsec
    nx_pixels = 64          # size of each postage stamp in pixels
    ny_pixels = 64
    nx_stamps = 10          # number of postage stamps in each direction
    ny_stamps = 10

    gal_flux_min = 1.e4     # Range for galaxy flux
    gal_flux_max = 1.e5  
    bulge_hlr_min = 0.3     # Range for bulge's half-light radius (arcsec)
    bulge_hlr_max = 0.9
    bulge_e_min = 0.        # Range for bulge's ellipticity
    bulge_e_max = 0.3
    bulge_frac_min = 0.1    # Range for bulge fraction
    bulge_frac_max = 0.5
    disk_hlr_min = 0.5      # Range for disk's half-light radius (arcsec)
    disk_hlr_max = 1.5
    disk_e_min = 0.2        # Range for disk's ellipticity
    disk_e_max = 0.8

    psf_fwhm = 0.65         # arcsec

    logger.info('Starting multi-object script 5')

    def draw_stamp(seed):
        """A function that draws a single postage stamp using a given seed for the 
           random number generator.
           Returns the image and the total time taken.
        """
        t1 = time.time()

        # Initialize the random number generator we will be using.
        rng = galsim.UniformDeviate(seed)

        # Make the pixel:
        pix = galsim.Pixel(xw = pixel_scale)

        # Make the PSF profile:
        psf = galsim.Moffat(fwhm = psf_fwhm, beta = 2.4)

        # Make the galaxy profile:
        hlr = rng() * (bulge_hlr_max-bulge_hlr_min) + bulge_hlr_min
        f = rng() * (bulge_frac_max-bulge_frac_min) + bulge_frac_min
        ellip = rng() * (bulge_e_max-bulge_e_min) + bulge_e_min
        beta_ellip = rng() * 2*math.pi * galsim.radians

        bulge = galsim.Sersic(n=3.6, half_light_radius=hlr, flux=f)
        bulge.applyShear(e=ellip, beta=beta_ellip)

        hlr = rng() * (disk_hlr_max-disk_hlr_min) + disk_hlr_min
        ellip = rng() * (disk_e_max-disk_e_min) + disk_e_min
        beta_ellip = rng() * 2*math.pi * galsim.radians

        disk = galsim.Sersic(n=1.5, half_light_radius=hlr)
        disk.applyShear(e=ellip, beta=beta_ellip)
        disk.setFlux(1.-f)

        gal = galsim.Add([bulge,disk])

        flux = rng() * (gal_flux_max-gal_flux_min) + gal_flux_min
        gal.setFlux(flux)

        # Build the final object by convolving the galaxy and PSF 
        # Not including the pixel -- since we are using drawShoot
        final_nopix = galsim.Convolve([psf, gal])

        # Define the stamp image
        stamp = galsim.ImageF(nx_pixels, ny_pixels)
        stamp.setScale(pixel_scale)

        # Photon shooting automatically convolves by the pixel, so we've made sure not
        # to include it in the profile!
        sky_level_pixel = sky_level * pixel_scale**2
        final_nopix.drawShoot(stamp, noise=sky_level_pixel/100, uniform_deviate=rng)

        # For photon shooting, galaxy already has poisson noise, so we want to make 
        # sure not to add that noise again!  Thus, we just add sky noise, which 
        # is Poisson with the mean = sky_level_pixel
        stamp.addNoise(galsim.PoissonDeviate(rng, mean=sky_level_pixel))

        t2 = time.time()
        return stamp, t2-t1

    def worker(input, output):
        """input is a queue with (seed, info) tuples:
               seed is the argement to pass to draw_stamp
               info is passed along to the output queue.
           output is a queue storing (result, info, proc) tuples:
               result is the returned tuple from draw_stamp: (image, time).
               info is passed through from the input queue.
               proc is the process name.
        """
        for (seed, info) in iter(input.get, 'STOP'):
            result = draw_stamp(seed)
            output.put( (result, info, current_process().name) )
    
    ntot = nx_stamps * ny_stamps

    # Take seeds to be sequential after the given seed value. 
    # This way different galaxies are deterministic, but uncorrelated.
    seeds = [ random_seed + k for k in range(ntot) ]

    # First draw the image using just a single process:
    t1 = time.time()
    image_single = galsim.ImageF(nx_stamps * nx_pixels , ny_stamps * ny_pixels)
    image_single.setScale(pixel_scale)

    k = 0
    for ix in range(nx_stamps):
        for iy in range(ny_stamps):
            bounds = galsim.BoundsI(ix*nx_pixels+1 , (ix+1)*nx_pixels, 
                                    iy*ny_pixels+1 , (iy+1)*ny_pixels)
            im, t = draw_stamp(seeds[k])
            image_single[bounds] = im
            proc = current_process().name
            logger.info('%s: Time for stamp (%d,%d) was %f',proc,ix,iy,t)
            k = k+1
    t2 = time.time()
    
    # Now do the same thing, but use multiple processes
    image_multi = galsim.ImageF(nx_stamps * nx_pixels , ny_stamps * ny_pixels)
    image_multi.setScale(pixel_scale)

    nproc = 4
    logger.info('Using ncpu = %d processes',nproc)

    # Set up the task list
    task_queue = Queue()
    k = 0
    for ix in range(nx_stamps):
        for iy in range(ny_stamps):
            task_queue.put( (seeds[k], [ix,iy]) ) 
            k = k+1
    
    # Run the tasks
    # Each Process command starts up a parallel process that will keep checking the queue 
    # for a new task. If there is one there, it grabs it and does it. If not, it waits 
    # until there is one to grab. When it finds a 'STOP', it shuts down. 
    done_queue = Queue()
    for k in range(nproc):
        Process(target=worker, args=(task_queue, done_queue)).start()

    # In the meanwhile, the main process keeps going.  We pull each image off of the 
    # done_queue and put it in the appropriate place on the main image.  
    # This loop is happening while the other processes are still working on their tasks.
    # You'll see that these logging statements get print out as the stamp images are still 
    # being drawn.  
    for i in range(ntot):
        result, info, proc = done_queue.get()
        ix = info[0]
        iy = info[1]
        bounds = galsim.BoundsI(ix*nx_pixels+1 , (ix+1)*nx_pixels, 
                                iy*ny_pixels+1 , (iy+1)*ny_pixels)
        im = result[0]
        image_multi[bounds] = im
        t = result[1]
        logger.info('%s: Time for stamp (%d,%d) was %f',proc,ix,iy,t)

    t3 = time.time()

    # Stop the processes
    # The 'STOP's could have been put on the task list before starting the processes, or you
    # can wait.  In some cases it can be useful to clear out the done_queue (as we just did)
    # and then add on some more tasks.  We don't need that here, but it's perfectly fine to do.
    # Once you are done with the processes, putting nproc 'STOP's will stop them all.
    # This is important, because the program will keep running as long as there are running
    # processes, even if the main process gets to the end.  So you do want to make sure to 
    # add those 'STOP's at some point!
    for k in range(nproc):
        task_queue.put('STOP')

    logger.info('Total time taken using a single process = %f',t2-t1)
    logger.info('Total time taken using %d processes = %f',nproc,t3-t2)

    # Now write the images to disk.
    image_single.write(single_file_name, clobber=True)
    image_multi.write(multi_file_name, clobber=True)
    logger.info('Wrote images to %r and %r',single_file_name, multi_file_name)

    numpy.testing.assert_array_equal(image_single.array, image_multi.array,
                                     err_msg="Images are not equal")
    logger.info('Images created using single and multiple processes are exactly equal.')
    logger.info('')

    print


def main(argv):
    try:
        # If no argument, run all scripts (indicated by scriptNum = 0)
        scriptNum = int(argv[1]) if len(argv) > 1 else 0
    except Exception as err:
        print __doc__
        raise err

    # Output files are put in the directory output.  Make sure it exists.
    if not os.path.isdir('output'):
        os.mkdir('output')

    # Setup logging here, rather than at module scope, so the user can do it
    # differently if they import the module and run the scripts as functions.
    # If this isn't called at all, no logging is done.
    # For fancy logging setups (e.g. when running on a big cluster) we could
    # use logging.fileConfig to use a config file to control logging.
    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG,
        stream=sys.stdout
    )

    # Script 1: Great08-like image
    if scriptNum == 0 or scriptNum == 1:
        Script1()

    # Script 2: Read parameters from catalog
    if scriptNum == 0 or scriptNum == 2:
        Script2()

    # Script 3: Real galaxies
    if scriptNum == 0 or scriptNum == 3:
        Script3()

    # Script 4: Photon shooting
    if scriptNum == 0 or scriptNum == 4:
        Script4()

    # Script 5: Multiple processes
    if scriptNum == 0 or scriptNum == 5:
        Script5()

if __name__ == "__main__":
    main(sys.argv)