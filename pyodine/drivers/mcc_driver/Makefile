CC=clang --std=gnu11
SRCS=usb-1608G.c

# RULES

libmccdaq:	libmccdaq.c usb-1608G.o libmccusb.a
	$(CC) -g -Weverything -I. -o $@ $@.c -L. -lmccusb  -lm -L/usr/local/lib -lhidapi-libusb -lusb-1.0 

%.d: %.c
	set -e; $(CC) -I. -M $(CPPFLAGS) $< \
	| sed 's/\($*\)\.o[ :]*/\1.o $@ : /g' > $@; \
	[ -s $@ ] || rm -f $@
ifneq ($(MAKECMDGOALS),clean)
include $(SRCS:.c=.d)
endif

clean:
	rm *.o *.d libmccdaq
