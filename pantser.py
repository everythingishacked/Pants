import cv2
import mediapipe as mp
import pyvirtualcam

import argparse
from datetime import datetime
import os
import sys


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--input', '-i', help='Input video device or file (number or path), defaults to 0', default=0)
  parser.add_argument('--flip', '-f', help='Set to any value to flip resulting output (selfie view)')
  parser.add_argument('--landmarks', '-l', help='Set to any value to draw body landmarks')
  parser.add_argument('--pants', '-p', help='Set to any value to draw on pants (not just blur)')
  parser.add_argument('--record', '-r', help='Set to any value to save a timestamped AVI in current directory')
  parser.add_argument('--width', '-w', help='Hip width, defaults to 0.4', default=0.4)
  args = parser.parse_args()

  INPUT = int(args.input) if (args.input and args.input.isdigit()) else args.input
  FLIP = args.flip is not None
  DRAW_LANDMARKS = args.landmarks is not None
  DRAW_PANTS = args.pants is not None
  RECORD = args.record is not None
  try:
    HIP_WIDTH = float(args.width)
  except:
    return print("Error: hip width must be a float")

  cap = cv2.VideoCapture(INPUT)

  MAX_PATTERNS = len([f for f in os.listdir('pants') if f.endswith(".png")])
  pattern = 0

  last_eye_height = 9001 # track moving head up out of frame

  if RECORD:
    RECORDING_FILENAME = str(datetime.now()).replace('.','').replace(':','') + '.avi'
    FPS = 10
    frame_size = (int(cap.get(3)), int(cap.get(4)))
    recording = cv2.VideoWriter(
      RECORDING_FILENAME, cv2.VideoWriter_fourcc(*'MJPG'), FPS, frame_size)

  with mp.solutions.pose.Pose() as pose:
    success, frame1 = cap.read() # grab initial frame to size matching virtual cam
    if not success:
      return print("Failed to read input source: {}".format(INPUT))

    with pyvirtualcam.Camera(width=frame1.shape[1], height=frame1.shape[0], fps=20) as cam:
      print(f'Using virtual camera: {cam.device}')

      while cap.isOpened():
        success, image = cap.read()
        if not success: break

        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = pose.process(image)

        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if DRAW_LANDMARKS:
          mp.solutions.drawing_utils.draw_landmarks(
              image,
              results.pose_landmarks,
              mp.solutions.pose.POSE_CONNECTIONS,
              landmark_drawing_spec=mp.solutions.drawing_styles.get_default_pose_landmarks_style())

        if results.pose_landmarks:
          body = []
          for point in results.pose_landmarks.landmark:
            body.append({
               'x': point.x,
               'y': point.y,
               'visibility': point.visibility
             })

          eyeL = body[2]
          eyeR = body[5]
          mouthL = body[9]
          mouthR = body[10]
          shoulderL = body[11]
          shoulderR = body[12]
          hipL = body[23]
          hipR = body[24]
          kneeL = body[25]
          kneeR = body[26]
          ankleL = body[27]
          ankleR = body[28]

          # TEMP mouth-hips, shoulder-knees for testing:
          # hipL = body[9]
          # hipR = body[10]
          # kneeL = body[11]
          # kneeR = body[12]

          if eyeL['visibility'] and eyeR['visibility']:
            last_eye_height = min(eyeL['y'], eyeR['y'])

          if (hipL['visibility'] > .2) and (hipR['visibility'] > .2):
            waistL_height = get_waist_height(hipL, shoulderL, kneeL)
            waistR_height = get_waist_height(hipR, shoulderR, kneeR)

            topY = int(min(waistL_height, waistR_height) * image.shape[0])
            bottomY = int(min(ankleL['y']*image.shape[0],
                              ankleR['y']*image.shape[0], image.shape[0]))
            rightX = int(hipR['x'] * image.shape[1])
            leftX = int(hipL['x'] * image.shape[1])

            minX, maxX = min(leftX, rightX), max(leftX, rightX)
            minY, maxY = min(topY, bottomY), max(topY, bottomY)
            width = maxX - minX
            height = maxY - minY

            # expand from center of legs to outside of hips
            hip_buffer = int(HIP_WIDTH * width)
            minX -= hip_buffer
            maxX += hip_buffer
            width += 2 * hip_buffer

            if width > 0 and height > 0 and minX > 0 and minY > 0 and maxX <= image.shape[1] and maxY <= image.shape[0]:
              zone = image[minY:maxY, minX:maxX]
              try:
                image[minY:maxY, minX:maxX] = cv2.GaussianBlur(zone, (75,75), 0)
              except:
                pass

              if DRAW_PANTS:
                pants = cv2.imread('pants/{}.png'.format(pattern), cv2.IMREAD_UNCHANGED)

                # cut off pants at 1/3, 2/3
                if kneeL['visibility'] < .1 or kneeR['visibility'] < .1:
                  pants = pants[:int(pants.shape[0]/3), :, :]
                elif ankleL['visibility'] < .1 or ankleR['visibility'] < .1:
                  pants = pants[:int(2*pants.shape[0]/3), :, :]

                pants = cv2.resize(pants, (width, height))
                alpha_s = pants[:, :, 3] / 255.0
                alpha_l = 1.0 - alpha_s
                for c in range(0, 3):
                  image[minY:maxY, minX:maxX, c] = (
                    alpha_s * pants[:, :, c] + alpha_l * image[minY:maxY, minX:maxX, c])

                try: # blend pants edges
                  image[minY:maxY, minX:maxX] = cv2.GaussianBlur(image[minY:maxY, minX:maxX], (5,5), 0)
                except:
                  pass
          elif last_eye_height < 0:
            # better safe than sorry; if eyes left top of screen, blur bottom third
            minY = int(image.shape[0] * 2/3)
            maxY = image.shape[0]
            bottom_third = image[minY:maxY, :]
            try:
              image[minY:maxY, :] = cv2.GaussianBlur(bottom_third, (75,75), 0)
            except:
              pass

        if FLIP:
          image = cv2.flip(image, 1) # selfie flip

        cv2.imshow('Preview', image) # remove if you don't want a preview window
        key = cv2.waitKey(1)
        if key == 27: # ESC to quit
          break
        elif key == ord('p'):
          if DRAW_PANTS:
            pattern += 1
            pattern %= MAX_PATTERNS
          else:
            DRAW_PANTS = True

        if RECORD:
          recording.write(image)

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        cam.send(image)
        cam.sleep_until_next_frame()

  cap.release()
  if RECORD:
    recording.release()


def get_waist_height(hip, shoulder, knee, toes=None):
  waist_height = hip['y']
  # TODO: customizable relative height of pants above waist
  if (shoulder['visibility'] > .2):
    waist_height += (shoulder['y'] - hip['y']) / 6
  elif (knee['visibility'] > .2):
    waist_height += (hip['y'] - knee['y']) / 8
  return waist_height


if __name__ == '__main__':
    main()
