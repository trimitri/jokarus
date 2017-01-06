CC=clang
CFLAGS=--std=gnu11 -Weverything

# RULES

franztest.elf: franztest.o libmccdaq.o
	$(CC) $(CFLAGS) -o $@ $^ -lm -L/usr/local/lib -lhidapi-libusb -lusb-1.0 -lmccusb

%.o: %.c
	$(CC) $(CFLAGS) -c $<

clean:
	rm *.o *.elf
