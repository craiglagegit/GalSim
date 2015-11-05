import numpy as np
import galsim

try:
    import lsst.pex.logging as pexLog
    import lsst.afw.geom as afwGeom
    import lsst.afw.cameraGeom as cameraGeom
    from lsst.afw.cameraGeom import PUPIL, PIXELS
    from lsst.obs.lsstSim import LsstSimMapper
except ImportError:
    raise ImportError("You cannot use the LSST module.\n"
                      "You either do not have the LSST stack installed,\n"
                      "or you have it installed, but have not set it up.\n"
                      "------------\n"
                      "To install the LSST stack, follow the instructions at:\n\n"
                      "https://confluence.lsstcorp.org/display/SIM/Catalogs+and+MAF\n\n"
                      "NOTE: you must build the stack with the python you are using to\n"
                      "run GalSim.  This means that when the stack asks you if you want\n"
                      "it to install Anaconda for you , you MUST SAY NO.\n\n"
                      "------------\n"
                      "If you have installed the stack, run\n\n"
                      "source $LSST_HOME/loadLSST.bash\n"
                      "setup obs_lsstSim -t sims\n")


__all__ = ["LSSTWCS"]

class LSSTWCS(galsim.wcs.CelestialWCS):

    def __init__(self, origin, rotation_angle):
        """
        inputs
        ------------
        origin is a CelestialCoord indicating the direction the telescope is pointing

        rotation_angle is an angle indicating the orientation of the camera with
        respect to the sky.  The convention for rotation_angle is:

        rotSkyPos = 0 degrees means north is in the +y direction on the camera and east is -x

        rotSkyPos = 90 degrees means north is -x and east is -y

        rotSkyPos = -90 degrees means north is +x and east is +y

        rotSkyPos = 180 degrees means north is -y and east is +x

        Note that in the above, x and y return to coordinates on the pupil.  These are
        rotated 90 degrees with respect to coordinates on the camera (pixel coordinates)
        because of the LSST Data Management convention that the x-direction in pixel
        coordinates must be oriented along the direction of serial readout.
        """

        # this line prevents the camera mapper from printing harmless warnings to
        # stdout (which, as of 5 November 2015, happens every time you instantiate
        # the camera below)
        pexLog.Log.getDefaultLog().setThresholdFor("CameraMapper", pexLog.Log.FATAL)

        self._camera = LsstSimMapper().camera

        self._pointing = origin
        self._rotation_angle = rotation_angle
        self._cos_rot = np.cos(self._rotation_angle/galsim.radians)
        self._sin_rot = np.sin(self._rotation_angle/galsim.radians)


    def _get_pupil_coordinates(self, point):
        """
        Convert from RA, Dec into coordinates on the pupil

        inputs
        ------------
        point is a CelestialCoord (or a list of CelestialCoords) indicating
        the positions to be transformed

        outputs
        ------------
        The x and y coordinates on the pupil in radians
        """

        if not hasattr(point, '__len__'):
            pt = self._pointing.project(point, projection='gnomonic')
            x = pt.x
            y = pt.y
        else:
            x = []
            y = []
            for pp in point:
                pt = self._pointing.project(pp, projection='gnomonic')
                x.append(pt.x)
                y.append(pt.y)
            x = np.array(x)
            y = np.array(y)

        return (x*self._cos_rot - y*self._sin_rot)*galsim.arcsec, \
               (x*self._sin_rot + y*self._cos_rot)*galsim.arcsec


    def _get_chip_name(self, point):
        """
        Take a point on the sky and find the chip which sees it

        inputs
        ------------
        point is a CelestialCoord (or a list of CelestialCoords) indicating
        the positions to be transformed

        outputs
        ------------
        the name of the chip (or a list of the names of the chips) on which
        those points fall
        """

        x_pupil, y_pupil = self._get_pupil_coordinates(point)

        if hasattr(x_pupil, '__len__'):
            camera_point_list = [afwGeom.Point2D(x/galsim.radians, y/galsim.radians) for x,y in zip(x_pupil, y_pupil)]
        else:
            camera_point_list = [afwGeom.Point2D(x_pupil/galsim.radians, y_pupil/galsim.radians)]

        det_list = self._camera.findDetectorsList(camera_point_list, PUPIL)

        chip_name_list = []

        for pt, det in zip(camera_point_list, det_list):
            if len(det)==0 or np.isnan(pt.getX()) or np.isnan(pt.getY()):
                chip_name_list.append(None)
            else:
                names = [dd.getName() for dd in det]
                if len(names)>1:
                    raise RuntimeError("This method does not know how to deal with cameras " +
                                       "where points can be on multiple detectors.  " +
                                       "Override LSSTWCS._get_chip_name to add this.")
                elif len(names)==0:
                    chip_name_list.append(None)
                else:
                    chip_name_list.append(names[0])

        if len(camera_point_list)==1:
            return chip_name_list[0]
        else:
            return chip_name_list