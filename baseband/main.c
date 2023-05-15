/**
 * Tobias Mages & Wenqing Yan
 * Backscatter PIO
 * 02-March-2023
 */

#include "backscatter.pio.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "math.h"
#include "packet_generation.h"
#include "pico/stdlib.h"
#include <stdio.h>

#if USE_ECC == 1
#define TX_DURATION 30
#elif USE_FEC == 1
#define TX_DURATION 6
#else
#define TX_DURATION 10
#endif

#define RECEIVER 1352  // define the receiver board either 2500 or 1352
#define PIN_TX1 6
#define PIN_TX2 27

int main()
{
  PIO pio = pio0;
  uint sm = 0;
  uint offset = pio_add_program(pio, &backscatter_program);
  backscatter_program_init(pio, sm, offset, PIN_TX1, PIN_TX2); // two antenna setup
  // backscatter_program_init(pio, sm, offset, PIN_TX1); // one antenna setup

#if USE_FEC == 1
  static uint8_t message[buffer_size(PAYLOADSIZE + 3, HEADER_LEN) * 4] = {0}; // include 10 header bytes
#else
  static uint8_t message[buffer_size(PAYLOADSIZE + 2, HEADER_LEN) * 4] = {0}; // include 10 header bytes
#endif
  static uint32_t buffer[buffer_size(PAYLOADSIZE, HEADER_LEN)] = {0};         // initialize the buffer
  static uint8_t seq = 0;
  uint8_t *header_tmplate = packet_hdr_template(RECEIVER);
  uint8_t tx_payload_buffer[PAYLOADSIZE];

#if USE_FEC == 1
  init_walsh();
#endif

  while (true)
  {
    /* generate new data */
    generate_data(tx_payload_buffer, PAYLOADSIZE, true);

    /* add header (10 byte) to packet */
    add_header(&message[0], seq, header_tmplate);
    /* add payload to packet */
    memcpy(&message[HEADER_LEN], tx_payload_buffer, PAYLOADSIZE);

    /* casting for 32-bit fifo */
    for (uint8_t i = 0; i < buffer_size(PAYLOADSIZE, HEADER_LEN); i++)
    {
      buffer[i] = ((uint32_t)message[4 * i + 3]) | (((uint32_t)message[4 * i + 2]) << 8) | (((uint32_t)message[4 * i + 1]) << 16) | (((uint32_t)message[4 * i]) << 24);
    }
    /* put the data to FIFO */
    backscatter_send(pio, sm, buffer, buffer_size(PAYLOADSIZE, HEADER_LEN));
    seq++;
    sleep_ms(TX_DURATION);
  }
}
