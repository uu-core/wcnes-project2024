/**
 * Tobias Mages & Wenqing Yan
 * Backscatter PIO
 * 02-March-2023
 */

#include <stdio.h>
#include "math.h"
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "backscatter.pio.h"
#include "packet_generation.h"

#define TX_DURATION 250 // send a packet every 250ms (when changing baud-rate, ensure that the TX delay is larger than the transmission time)
#define RECEIVER 1352 // define the receiver board either 2500 or 1352
#define PIN_TX1 6
#define PIN_TX2 27
#define PL_1 1

int main() {
    PIO pio = pio0;
    uint sm = 0;
    uint offset = pio_add_program(pio, &backscatter_program);
    backscatter_program_init(pio, sm, offset, PIN_TX1, PIN_TX2); // two antenna setup
    //backscatter_program_init(pio, sm, offset, PIN_TX1); // one antenna setup

    static uint8_t message[buffer_size(PL_1+2, 0)*4] = {0};  // include 10 header bytes
    static uint32_t buffer[buffer_size(PL_1, HEADER_LEN)] = {0}; // initialize the buffer
    static uint8_t seq = 0;
    uint8_t *header_tmplate = packet_hdr_template(RECEIVER);
    uint8_t tx_payload_buffer[PL_1];


    while (true) {
        /* generate new data */
        //generate_data(tx_payload_buffer, PL_1, true);
        
        //generate_static_data(tx_payload_buffer, PL_1, true);


        /* add header (10 byte) to packet */
        //add_header(&message[0], seq, header_tmplate);
        /* add payload to packet */
        memcpy(&message[0], tx_payload_buffer, PL_1);

        /* casting for 32-bit fifo */
        //for (uint8_t i=0; i < buffer_size(PL_1, 0); i++) {
        //    buffer[i] = ((uint32_t) message[4*i+3]) | (((uint32_t) message[4*i+2]) << 8) | (((uint32_t) message[4*i+1]) << 16) | (((uint32_t)message[4*i]) << 24);
        //}
        buffer[0] = 0b11111111111111111111111111001001;
        /* put the data to FIFO */
        backscatter_send(pio,sm,buffer,1);
        seq++;
        sleep_ms(TX_DURATION);
    }
}
