CC=clang
CFLAGS=--std=gnu11 -march=native -O3 -Weverything -pedantic 

# RULES

all: franztest.elf shared-franztest.elf

franztest.elf: franztest.o libmccdaq.o
	$(CC) $(CFLAGS) -o $@ $^ -lm -lhidapi-libusb -lusb-1.0 -lmccusb

# a variant of franztest that uses libmccdaq.so as shared library
shared-franztest.elf: franztest.c libmccdaq.so
	$(CC) -L. $(CFLAGS) -o $@ $< -lmccdaq -lmccusb -lhidapi-libusb -lusb-1.0 -lm 

%.o: %.c
	$(CC) $(CFLAGS) -c $<

%.oPIC: %.c
	$(CC) $(CFLAGS) -o $@ -fPIC -c $<

libmccdaq.so: libmccdaq.oPIC
	$(CC) -fPIC -shared -o libmccdaq.so libmccdaq.oPIC
