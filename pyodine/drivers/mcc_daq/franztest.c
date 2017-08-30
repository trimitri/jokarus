#include <stdlib.h>
#include <stdio.h>
#include "libmccdaq.h"

int main() {

  OpenConnection();
  /*
  TriangleOnce(1., -10, 10);
  uint8_t channels[] = {10, 11, 12};
  uint n_channels = sizeof(channels);
  uint n_samples = 600;
  double frequency = 500;

  double * data = calloc(n_samples * n_channels, sizeof(double));
  SampleChannelsAt10V(channels, n_channels, n_samples, frequency, data);
  for (uint sample = 0; sample < n_samples; sample++) {
    for (uint channel = 0; channel < n_channels; channel++) {
      printf("%10g  ", (double) data[sample * n_channels + channel]);
    }
    printf("\n");
  }
  free(data);
  */

  double * data = calloc(LIBMCCDAQ_BULK_TRANSFER_SIZE * 2, sizeof(double));
  int ret = FetchScan(0., 1., 1., kDescent, data);
  printf("%d\n", ret);
  for (uint i = 0; i < LIBMCCDAQ_BULK_TRANSFER_SIZE; i++) {
    if (i % 50 == 0) {
      printf("%g\t%g\n", data[2*i], data[2*i + 1]);
    }
  }
}
