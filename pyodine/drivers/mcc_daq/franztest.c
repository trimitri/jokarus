#include <stdio.h>
#include "libmccdaq.h"

int main() {

  libusb_device_handle *dev = OpenConnection();

  Triangle(dev);
  uint16_t amps[1024];
  GenerateTriangleSignal(1024, amps);
}
