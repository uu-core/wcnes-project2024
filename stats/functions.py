#!/Users/wenya589/.pyenv/shims/python
#
# Copyright 2023, 2023 Wenqing Yan <yanwenqingindependent@gmail.com>
#
# This file is part of the pico backscatter project
# Analyze the communication systme performance with the metrics (time, reliability and distance).
import math
from io import StringIO
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy import NaN
from pylab import rcParams
rcParams["figure.figsize"] = 16, 4

# NOTE: This order is based on the C code, DO NOT CHANGE!
walsh_combinations = [
    [0,0,0,0],
    [0,0,0,1],
    [0,0,1,0],
    [0,0,1,1],
    [0,1,0,0],
    [0,1,0,1],
    [0,1,1,0],
    [0,1,1,1],
    [1,0,0,0],
    [1,0,0,1],
    [1,0,1,0],
    [1,0,1,1],
    [1,1,0,0],
    [1,1,0,1],
    [1,1,1,0],
    [1,1,1,1],
]

# Generating large comparision files takes a lot time.
# Since they only depend on the packet length, we can
# cache the output in a dict with the length as key.
cached_comparison_files = {}

def get_walsh_codes(order):
    #basic element(seed) of walsh code generator
    W = np.array([0])
    for i in range(order):
        W = np.tile(W, (2, 2))
        half = 2**i
        W[half:, half:] = np.logical_not(W[half:, half:])
    return W

# read the log file
def readfile(filename):
    types = {
        "time_rx": str,
        "frame": str,
        "rssi": str,
    }
    df = pd.read_csv(
        StringIO(" ".join(l for l in open(filename))),
        skiprows=0,
        header=None,
        dtype=types,
        delim_whitespace=False,
        delimiter="|",
        on_bad_lines='warn',
        names=["time_rx", "frame", "rssi"]
    )
    df.dropna(inplace=True)
    # covert to time data type
    df.time_rx = df.time_rx.str.rstrip().str.lstrip()
    df.time_rx = pd.to_datetime(df.time_rx, format='%H:%M:%S.%f')
    for i in range(len(df)):
        df.iloc[i, 0] = df.iloc[i, 0].strftime("%H:%M:%S.%f")
    # parse the payload to seq and payload
    df.frame = df.frame.str.rstrip().str.lstrip()
    df = df[df.frame.str.contains("packet overflow") == False]
    df['seq'] = df.frame.apply(lambda x: int(x[3:5], base=16))
    df['payload'] = df.frame.apply(lambda x: x[6:])
    # parse the rssi data
    df.rssi = df.rssi.str.lstrip().str.split(" ", expand=True).iloc[:, 0]
    df.rssi = df.rssi.astype('int')
    df = df.drop(columns=['frame'])
    df.reset_index(inplace=True)
    return df

# parse the hex payload, return a list with int numbers for each byte
def parse_payload(payload_string, USE_ECC=False, USE_FEC=False):
    if USE_ECC:
        # yes
        binary = list(
            map(lambda x: list(format(int(x, base=16), "0>8b")), payload_string.split()))
        flat_binary = [item for sublist in binary for item in sublist]
        bits = [flat_binary[i:i+3] for i in range(0, len(flat_binary), 3)]
        tmp = list(map(lambda x: 0 if x.count("0") > 1 else 1, bits))
        return list(map(lambda x: int("".join(str(c) for c in x), base=2), [tmp[i:i+8] for i in range(0, len(tmp), 8)]))
    elif USE_FEC:
        walsh_codes = get_walsh_codes(4)
        binary = list(
            map(lambda x: list(format(int(x, base=16), "0>8b")), payload_string.split()))
        flat_binary = [item for sublist in binary for item in sublist]
        # TODO: We can repeat the sample position 4 times on the transmitter. This way, we
        #       can be more certain that the position is correct, even if we have bit errors.
        sample_position = "".join(str(b) for b in flat_binary[6:8]) # Sample position is between 0-3, i.e. 2 bits of data
        data = [int(bit) for bit in flat_binary[8:]]
        values = []
        # Multiply each code with the received data (dot product).
        # The with the largest value will
        for code in walsh_codes:
            values.append(np.dot(np.array(data), np.array(code)))
        # Get the Walsh code that is closest to the received bits
        bits = walsh_combinations[np.argmax(np.array(values))]
        # Need to pad to get a full byte (2 bit sample position + 4 bit data)
        return [int("00" + sample_position + "".join(str(b) for b in bits), base=2)]
    else:
        tmp = map(lambda x: int(x, base=16), payload_string.split())
        return list(tmp)

def popcount(n):
    return bin(n).count("1")

# compare the received frame and transmitted frame and compute the number of bit errors
def compute_bit_errors(payload, sequence, PACKET_LEN=32, USE_FEC=False):
    if not USE_FEC:
        return sum(
            map(
                popcount,
                (
                    np.array(payload[:PACKET_LEN])
                    ^ np.array(sequence[:len(payload[:PACKET_LEN])])
                ),
            )
        )

    # Payload is only 1 byte once parsed
    sample_position = (payload[0] >> 4) & 0x03
    data = payload[0] & 0x0F
    # Sequence is a list of 2 bytes for FEC (1 sample),
    # get the correct one based on the sample position (0-1 is left byte, 2-3 is right byte)
    sample_byte = sequence[0 if sample_position < 2 else 1]
    sample_data = (sample_byte >> (4 if (sample_position % 2) else 0)) & 0x0F
    return bin(data ^ sample_data).count("1")

# deal with seq field overflow problem, generate ground-truth sequence number
def replace_seq(df, MAX_SEQ):
    df['new_seq'] = None
    count = 0
    df.iloc[0, df.columns.get_loc('new_seq')] = df.seq[0]
    for idx in range(1, len(df)):
        if df.seq[idx] < df.seq[idx-1] - 50:
            count += 1
            # for the counter reset scanrio, replace the seq value with order
        df.iloc[idx, df.columns.get_loc(
            'new_seq')] = MAX_SEQ*count + df.seq[idx]
    return df

# a 8-bit random number generator with uniform distribution
def rnd(seed):
    A1 = 1664525
    C1 = 1013904223
    RAND_MAX1 = 0xFFFFFFFF
    seed = ((seed * A1 + C1) & RAND_MAX1)
    return seed

# a 16-bit generator returns compressible 16-bit data sample
def data(seed):
    two_pi = np.float64(2.0 * np.float64(math.pi))
    u1 = 0
    u2 = 0
    while (u1 == 0 or u2 == 0):
        seed = rnd(seed)
        u1 = np.float64(seed/0xFFFFFFFF)
        seed = rnd(seed)
        u2 = np.float64(seed/0xFFFFFFFF)
    tmp = 0x7FF * \
        np.float64(math.sqrt(np.float64(-2.0 * np.float64(math.log(u1)))))
    return np.trunc(max([0, min([0x3FFFFF, np.float64(np.float64(tmp * np.float64(math.cos(np.float64(two_pi * u2)))) + 0x1FFF)])])), seed

# generate the transmitted file for comparison
# generate a 40MB file, in case transmit too many data (larger than required 2MB)
TOTAL_NUM_16RND = 512*40*64
def generate_data(NUM_16RND, TOTAL_NUM_16RND):
    LOW_BYTE = (1 << 8) - 1
    length = int(np.ceil(TOTAL_NUM_16RND/NUM_16RND))
    index = [NUM_16RND*i*2 for i in range(length)]
    df = pd.DataFrame(index=index, columns=['data'])
    seed = 0xabcd  # initial seed
    for i in index:
        payload_data = []
        for j in range(NUM_16RND):
            number, seed = data(seed)
            payload_data.append((int(number) >> 8) - 0)
            payload_data.append(int(number) & LOW_BYTE)
        df.data[i] = payload_data
    return df

# main function to compute the BER for each frame, return both the error statistics dataframe and in total BER for the received data
def compute_ber(df, PACKET_LEN=32, MAX_SEQ=256, USE_ECC=False, USE_FEC=False):
    packets = len(df)
    total_transmitted_packets = df.seq[packets-1]+1

    # dataframe records the bit error for each packet, use the seq number as index
    error = pd.DataFrame(columns=["seq", "bit_error_tmp"])
    # seq number initialization
    # print(f"The total number of packets transmitted by the tag is {total_transmitted_packets}.")
    error.seq = range(df.seq[0], df.seq[packets-1]+1)
    # bit_errors list initialization
    error.bit_error_tmp = [list() for x in range(len(error))]
    # compute in total transmitted file size
    file_size = len(error) * PACKET_LEN * 8
    # The number of samples we need in the comparision files
    samples_in_file = (df.seq[packets-1]+1)*(PACKET_LEN/2)

    # generate the correct file
    file_content = None
    cached_file = cached_comparison_files.get(PACKET_LEN)
    if cached_file is None or cached_file[1] < samples_in_file:
        file_content = generate_data(int(PACKET_LEN/2), samples_in_file)
        cached_comparison_files[PACKET_LEN] = (samples_in_file, file_content)
    else:
        # The file has been generated, and the size is large enough
        file_content = cached_file[1]

    last_pseudoseq = 0  # record the previous pseudoseq
    # start count the error bits
    for idx in range(packets):
        # return the matched row index for the specific seq number in log file
        error_data = error.index[error.seq == df.seq[idx]]
        if error_data.size == 0:
            # No packet with this sequence was received.
            # This will result in the entire packet payload being considered as error (see below)
            continue
        error_idx = error_data[0]
        # parse the payload and return a list, each element is 8-bit data, the first 16-bit data is pseudoseq
        payload = parse_payload(df.payload[idx], USE_ECC=USE_ECC, USE_FEC=USE_FEC)

        # TODO: What is this? The payload does not contain the first 2 bytes containing the sequence, etc.
        pseudoseq = int(((payload[0] << 8) - 0) + payload[1])
        sample_index = pseudoseq
        if USE_FEC:
            # 4 packets need to be received in order to get a full sample
            sample_index = pseudoseq // 4

        # deal with bit error in pseudoseq
        if sample_index not in file_content.index:
            if USE_FEC:
                # Only go to the next sample in the generated data if the last received
                # packet was the last packet for the current sample.
                if (last_pseudoseq % 4) == 3:
                    pseudoseq = last_pseudoseq + PACKET_LEN
                    sample_index = pseudoseq // 4
            else:
                pseudoseq = last_pseudoseq + PACKET_LEN
                sample_index = pseudoseq

        # TODO: Keep track of sample_position relative to pseudoseq in order to correct
        #       potential errors in the sample position byte.

        # compute the bit errors
        error.bit_error_tmp[error_idx].append(compute_bit_errors(payload[2:], file_content.loc[sample_index, 'data'], PACKET_LEN=PACKET_LEN, USE_FEC=USE_FEC))
        last_pseudoseq = pseudoseq

    # initialize the total bit error counter for entire file
    counter = 0
    bit_error = []
    # for the lost packet
    for l in error.bit_error_tmp:
        if l == []:
            if USE_FEC:
                counter += 4 # 4-bits of data transmitted per packet payload
            else:
                counter += PACKET_LEN*8  # when the seq number is lost, consider the entire packet payload as error
        else:
            tmp = min(l)
            counter += tmp  # when the seq number received several times, consider the minimum error
        bit_error.append(tmp)
    # update the bit_error column
    error['bit_error'] = bit_error
    # error = error.drop(columns='bit_error_tmp')
    # print("Error statistics dataframe is:")
    # print(error)

    # Calculate etx
    etx = total_transmitted_packets/packets
    return counter / file_size, error, etx

# plot radar chart
def radar_plot(metrics, title=None):
    categories = ['Time', 'Reliability', 'Distance']
    system_ref = [62.321888, 0.201875*100, 39.956474923886844]
    system = [metrics[0], metrics[1], metrics[2]]

    label_loc = np.linspace(start=0.5 * np.pi, stop=11 /
                            6 * np.pi, num=len(categories))
    plt.figure(figsize=(8, 8))
    plt.subplot(polar=True)

    # please keep the reference for your plot, we will update the reference after each SR session
    plt.plot(np.append(label_loc, (0.5 * np.pi)), system_ref +
             [system_ref[0]], label='Reference', color='grey')
    plt.fill(label_loc, system_ref, color='grey', alpha=0.25)

    plt.plot(np.append(label_loc, (0.5 * np.pi)), system +
             [system[0]], label='Our system', color='#77A136')
    plt.fill(label_loc, system, color='#77A136', alpha=0.25)

    if title is None:
        plt.title('System Performance', size=20)
    else:
        plt.title(title, size=20)

    lines, labels = plt.thetagrids(np.degrees(
        label_loc), labels=categories, fontsize=18)
    plt.legend(fontsize=18, loc='upper right')
    plt.show()
