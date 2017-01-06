#include "libmccdaq.h"

int main() {
  libusb_device_handle *dev = OpenConnection();
  float out_cal[NCHAN_AO_1608GX][2];
  float in_cal[NGAINS_1608G][2];
  GenerateCalibrationTable(dev, in_cal, out_cal); 
  Sawtooth(dev, out_cal);
}
