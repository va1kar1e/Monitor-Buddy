#pragma once
// The Buddy as a USB mouse (firmware env esp32-s3-hid only; this file is not built for the
// others, see build_src_filter in platformio.ini). It is its own file because the library
// finder does not evaluate #ifdef: only a file that is left out of the build keeps the
// Arduino USB library out of the other environments.
#include <stdint.h>

// Adds the HID interface. Call before USB.begin(), which enumerates the device.
void hidMouseBegin();
// A relative move of the pointer, -127..127 on each axis.
void hidMouseMove(int8_t dx, int8_t dy);
