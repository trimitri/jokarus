#include <stdlib.h>
#include <stdio.h>
#include "libmccdaq.h"

int main() {

  OpenConnection();
  TriangleOnce();
  uint8_t channels[] = {10, 11, 12};
  uint n_channels = sizeof(channels);
  uint n_samples = 100;
  double frequency = 1E2;

  float * data = NULL;
  data = SampleChannelsAt10V(channels, n_channels, n_samples, frequency);
  for (uint sample = 0; sample < n_samples; sample++) {
    for (uint channel = 0; channel < n_channels; channel++) {
      printf("%6g  ", (double) data[sample * n_channels + channel]);
    }
    printf("\n");
  }
  free(data);
}
