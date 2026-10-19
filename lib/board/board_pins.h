#pragma once
// Board support: which Waveshare board this firmware is built for, and what is
// wired where. platformio.ini sets exactly one of
//
//   BOARD_ESP32_C6_TOUCH_LCD_147   Waveshare ESP32-C6-Touch-LCD-1.47 (the original Buddy)
//   BOARD_ESP32_S3_TOUCH_LCD_147   Waveshare ESP32-S3-Touch-LCD-1.47
//
// With neither set, the chip decides (an ESP32-S3 build gets the S3 board), and
// anything else gets the C6 board, so older builds behave as before.
//
// Both boards carry the same 1.47" 172x320 module: JD9853 LCD on SPI and an
// AXS5106L touch controller (I2C 0x63). They differ in the pins, in the motion
// sensor (only the C6 board has the QMI8658) and in the BOOT button's GPIO.
//
// Every pin can be overridden from the build flags (-DLCD_BL=5, say), without
// editing this file. Two signals on one GPIO stop the build.
//
// This header is plain C preprocessor and constexpr: no Arduino types, so the
// checks at the bottom run on every build for either board.

#if !defined(BOARD_ESP32_C6_TOUCH_LCD_147) && !defined(BOARD_ESP32_S3_TOUCH_LCD_147)
  #if defined(CONFIG_IDF_TARGET_ESP32S3)
    #define BOARD_ESP32_S3_TOUCH_LCD_147
  #else
    #define BOARD_ESP32_C6_TOUCH_LCD_147
  #endif
#endif

#if defined(BOARD_ESP32_C6_TOUCH_LCD_147) && defined(BOARD_ESP32_S3_TOUCH_LCD_147)
  #error "Set only one of BOARD_ESP32_C6_TOUCH_LCD_147 and BOARD_ESP32_S3_TOUCH_LCD_147"
#endif

// ════════════════════════════════════════════════════════════
//  Waveshare ESP32-C6-Touch-LCD-1.47
// ════════════════════════════════════════════════════════════
#if defined(BOARD_ESP32_C6_TOUCH_LCD_147)

#define BOARD_NAME     "ESP32-C6"
#define BOARD_HAS_IMU  1          // QMI8658 on the touch I2C bus, address 0x6B

// Pins already taken on this board:
//   1, 2, 14, 15, 22, 23  → LCD SPI / DC / CS / RST / backlight
//   18, 19, 20, 21        → touch I2C / RST / INT
//   5, 6                  → QMI8658 IMU interrupts
//   8                     → boot-mode strapping + onboard RGB LED
//   9                     → BOOT button
//   12, 13                → USB-Serial-JTAG
// GPIO3 is free, broken out, and is not a strapping pin, so it is used as a
// harmless "status LED" sink: nothing is wired to it, AyresWiFiManager just
// toggles it. If you solder an LED to another free pin, change AWM_LED_PIN.
#ifndef LCD_BL
  #define LCD_BL    23
#endif
#ifndef LCD_DC
  #define LCD_DC    15
#endif
#ifndef LCD_CS
  #define LCD_CS    14
#endif
#ifndef LCD_SCK
  #define LCD_SCK    1
#endif
#ifndef LCD_MOSI
  #define LCD_MOSI   2
#endif
#ifndef LCD_RST
  #define LCD_RST   22
#endif

#ifndef TOUCH_SDA
  #define TOUCH_SDA 18
#endif
#ifndef TOUCH_SCL
  #define TOUCH_SCL 19
#endif
#ifndef TOUCH_RST
  #define TOUCH_RST 20
#endif
#ifndef TOUCH_INT
  #define TOUCH_INT 21
#endif

#ifndef AWM_LED_PIN
  #define AWM_LED_PIN     3       // dummy/optional status LED, must NOT be an LCD or touch pin
#endif
#ifndef AWM_BUTTON_PIN
  #define AWM_BUTTON_PIN  9       // onboard BOOT button, active LOW
#endif

// ════════════════════════════════════════════════════════════
//  Waveshare ESP32-S3-Touch-LCD-1.47
// ════════════════════════════════════════════════════════════
// Source: the board's schematic (ESP32-S3-Touch-LCD-1.47-Schematic.pdf), nets
// named in its netlist. Waveshare's Arduino demo gives LCD DC 45, CS 21,
// SCK 38, MOSI 39 (the same) but RST 47, and says its pins follow the
// ESP32-S3-Zero: the schematic puts LCD_RST on GPIO40 and TP_RST on GPIO47,
// so GPIO40 is used here. Not yet tried on a board: if the screen stays blank,
// swap the two from the build flags (-DLCD_RST=47 -DTOUCH_RST=40) to compare.
#elif defined(BOARD_ESP32_S3_TOUCH_LCD_147)

#define BOARD_NAME     "ESP32-S3"
#define BOARD_HAS_IMU  0          // no motion sensor on this board: the eyes use the fallback motion

// Pins already taken on this board:
//   21, 38, 39, 40, 45    → LCD CS / SCK / MOSI / RST / DC (SPI, write only)
//   46                    → LCD backlight, through a transistor (a strapping pin)
//   41, 42, 47, 48        → touch I2C SCL / SDA / RST / INT
//   13–18                 → TF card slot
//   12                    → battery voltage divider
//   19, 20                → USB D- / D+ (the native USB serial port)
//   33–37                 → the module's octal PSRAM; 26–32 its flash
//   0                     → BOOT button
//   3, 45, 46             → strapping pins
// GPIO4 is free, broken out on the header, and is not a strapping pin, so it
// is used as a harmless "status LED" sink, like GPIO3 on the C6 board.
#ifndef LCD_BL
  #define LCD_BL    46
#endif
#ifndef LCD_DC
  #define LCD_DC    45
#endif
#ifndef LCD_CS
  #define LCD_CS    21
#endif
#ifndef LCD_SCK
  #define LCD_SCK   38
#endif
#ifndef LCD_MOSI
  #define LCD_MOSI  39
#endif
#ifndef LCD_RST
  #define LCD_RST   40
#endif

#ifndef TOUCH_SDA
  #define TOUCH_SDA 42
#endif
#ifndef TOUCH_SCL
  #define TOUCH_SCL 41
#endif
#ifndef TOUCH_RST
  #define TOUCH_RST 47
#endif
#ifndef TOUCH_INT
  #define TOUCH_INT 48
#endif

#ifndef AWM_LED_PIN
  #define AWM_LED_PIN     4       // dummy/optional status LED, must NOT be an LCD or touch pin
#endif
#ifndef AWM_BUTTON_PIN
  #define AWM_BUTTON_PIN  0       // onboard BOOT button, active LOW
#endif

#endif  // board selection

// ── Checks, on every build ──────────────────────────────────
// Two signals on one pin would clamp each other: the SPI data line held by the
// status LED is what blanked the screen before AWM_LED_PIN was set explicitly.
namespace board_pins_check {
constexpr int kPins[] = {LCD_BL,    LCD_DC,    LCD_CS,    LCD_SCK,  LCD_MOSI,
                         LCD_RST,   TOUCH_SDA, TOUCH_SCL, TOUCH_RST, TOUCH_INT,
                         AWM_LED_PIN, AWM_BUTTON_PIN};
constexpr int kCount = sizeof(kPins) / sizeof(kPins[0]);
constexpr bool allDistinct() {
  for (int i = 0; i < kCount; i++)
    for (int j = i + 1; j < kCount; j++)
      if (kPins[i] == kPins[j]) return false;
  return true;
}
}  // namespace board_pins_check
static_assert(board_pins_check::allDistinct(),
              "board_pins.h: two signals share a GPIO (LCD, touch, status LED, BOOT button)");
