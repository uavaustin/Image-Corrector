import json
import os
from math import atan, tan, cos, sin, pi, sqrt, ceil
from shutil import copy2

import cv2
import numpy as np

class AerialImage:

    def __init__(self, corrector, file_name):
        self._corrector = corrector
        self._number = corrector.image_count + 1
        self._file_name = str(self._number) + '.' + \
            file_name.split('.')[1]
        self._position = None

        self._save_original(file_name)

        time = os.path.getmtime(
            self._corrector.image_folder + '/new/' + file_name
        )
        os.remove(self._corrector.image_folder + '/new/' + file_name)

        alert = json.dumps({
            'type': 'image',
            'message': {
                'type': 'alert',
                'format': 'original',
                'status': 'available'
            }
        })

        request = json.dumps({
            'type': 'telemetry',
            'message': {
                'type': 'request',
                'time': time,
                'image-number': self._number
            }
        })

        self._corrector.client.send(alert)
        self._corrector.client.send(request)

    def set_position(self, position):
        self._position = position

        did_warp = self._warp()

        alert = json.dumps({
            'type': 'image',
            'message': {
                'type': 'alert',
                'format': 'warped',
                'status': 'available' if did_warp else 'unavailable'
            }
        })

        self._corrector.client.send(alert)

    def _save_original(self, file_name):
        copy2(
            self._corrector.image_folder + '/new/' + file_name,
            self._corrector.image_folder + '/current/' + self._file_name
        )
        copy2(
            self._corrector.image_folder + '/new/' + file_name,
            self._corrector.image_folder + '/archive/' + \
            self._corrector.archive_name + '/' + self._file_name
        )

    @property
    def has_position(self):
        return self._position is not None

    def _warp(self):
        """
        warp the image using SimpleCV / OpenCV
        leave the corners of the warped image transparent
        save the warped image in /current/ and in /archive/ just
        as _save_original does return False if the horizon was visible.
        """

        image = cv2.imread(self._file_name,cv2.IMREAD_UNCHANGED)
        height, width, channels = image.shape

        if channels == 3:
            alpha = np.ones((rows,cols,1)) * 255
            image = np.concatenate((image,alpha), axis=2)

        corners = self._get_corner_pixels(image_width, image_height)

        if not corners:
            return False

        new_width = max[i[0] for i in corners]
        new_height = max[i[1] for i in corners]

        original_corners = np.float32(
            ((0, 0), (width - 1, 0), (width - 1, height - 1), (0 , height - 1))
        )
        new_corners = np.float32(corners)

        rot_matrix = cv2.getPerspectiveTransform(original_corners, new_corners)

        new_image = cv2.warpPerspective(
            src=image, dsize=(new_width, new_height), M=rot_matrix,
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_TRANSPARENT
        )

        # FIXME: Save as different file name from the original, this
        # currently replaces the original.
        cv2.imwrite(self._file_name, new_image)

        return True

    def _get_corner_pixels(self, image_width, image_height):

        corners = self._position.get_corner_distances(
            self._corrector.ASPECT_RATIO, self._corrector.HORIZ_FOV
        )

        if not corners:
            return None

        x = [int(i[0]) for i in corners]
        y = [int(i[1]) for i in corners]

        min_x = min(x)
        max_y = max(y)

        x = [i - min_x for i in x]
        y = [max_y - i for i in y]

        max_x = max(x)
        max_y = max(y)

        k = ceil(sqrt(2 * image_width * image_height / (max_x * max_y)))

        x = [i * k for i in x]
        y = [i * k for i in y]

        return [[x[i], y[i]] for i in range(len(corners))]

class Position:
    """Represents the position of a plane and its camera.

    All units are in radians and meters. For the plane, a yaw of 0
    radians points North and pi / 2 points East, a pitch of 0 radians
    is horizontal and a positive pitch points upwards, and a roll of
    0 radians is level and a positive roll indicates the plane has
    rolled to the right. For the camera, a pitch of 0 radians points
    downwards and a positive pitch points towards the front of the
    plane and a roll of 0 radians points to the center of the plane
    and a positive roll points to the right.
    """

    def __init__(self, lat, lon, alt, yaw, pitch, roll, cam_pitch, cam_roll):
        """Instantiate a Position object.

        All units are in radians and meters.
        """
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.yaw = yaw
        self.pitch = pitch
        self.roll = roll
        self.cam_pitch = cam_pitch
        self.cam_roll = cam_roll

    def get_distance(self, d_pitch=0, d_roll=0):
        """Return the ground distance of a camera's line of sight.

        d_pitch and d_roll are the angles above and to the left of
        where the center of the camera is pointing. A list is
        returned with first the Distance North and second the
        distance East in meters. None is returned if the camera is
        pointing at the sky.
        """
        alt = self.alt
        yaw = self.yaw
        pitch = self.pitch + self.cam_pitch + d_pitch
        roll = -self.roll + self.cam_roll + d_roll

        # FIXME: Improve is pointed at sky expression
        if abs(pitch) + d_pitch >= pi / 2 or abs(roll) + d_roll >= pi / 2:
            return None

        x = alt * (tan(roll) / cos(pitch) * cos(yaw) + tan(pitch) * sin(yaw))
        y = alt * (tan(pitch) * cos(yaw) - tan(roll) / cos(pitch) * sin(yaw))

        return [x, y]

    def get_corner_distances(self, aspect_ratio, horiz_fov):
        """Return the ground distance of the camera's corners.

        aspect_ratio is the ratio of the width to the height of the
        image and horiz_fov is the horizontal field of view of the
        camera in radians. A list of four lists of x and y pairs is
        returned in the order of top-left, top-right, bottom-right,
        and bottom-left corners from get_distance(). None is
        returned if the horizon is visible.
        """
        vert_fov = 2 * atan(tan(horiz_fov / 2) / aspect_ratio)

        corners = [
            self.get_distance(vert_fov / 2, -horiz_fov / 2),
            self.get_distance(vert_fov / 2, horiz_fov / 2),
            self.get_distance(-vert_fov / 2, horiz_fov / 2),
            self.get_distance(-vert_fov / 2, -horiz_fov / 2),
        ]

        if None in corners:
            print('Cannot warp image since horizon is visible.')

            return None

        return corners
