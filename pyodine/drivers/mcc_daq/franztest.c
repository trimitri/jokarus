#include <stdio.h>
#include "libmccdaq.h"

int main() {

  OpenConnection();
  TriangleOnce();
  SampleChannel(11);
}
