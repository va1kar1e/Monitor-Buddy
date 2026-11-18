#include "hid_mouse.h"

#include <USB.h>
#include <USBHIDMouse.h>

static USBHIDMouse mouse;

void hidMouseBegin() { mouse.begin(); }
void hidMouseMove(int8_t dx, int8_t dy) { mouse.move(dx, dy); }
