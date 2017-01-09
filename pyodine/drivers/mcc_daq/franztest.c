#include "libmccdaq.h"

int main() {

  libusb_device_handle *dev = OpenConnection();

  Sawtooth(dev);

}
