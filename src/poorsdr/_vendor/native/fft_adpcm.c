#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define POORSDR_EXPORT __declspec(dllexport)
#else
#define POORSDR_EXPORT __attribute__((visibility("default")))
#endif

static const int index_table[16] = {
    -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8
};

static const int step_table[89] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767
};

static int16_t decode_nibble(unsigned int nibble, int *step_index, int *predictor, int *step) {
    int diff;
    nibble &= 15U;
    *step_index += index_table[nibble];
    if (*step_index < 0) *step_index = 0;
    if (*step_index > 88) *step_index = 88;

    diff = *step >> 3;
    if (nibble & 1U) diff += *step >> 2;
    if (nibble & 2U) diff += *step >> 1;
    if (nibble & 4U) diff += *step;
    if (nibble & 8U) diff = -diff;
    *predictor += diff;
    if (*predictor < -32768) *predictor = -32768;
    if (*predictor > 32767) *predictor = 32767;
    *step = step_table[*step_index];
    return (int16_t)*predictor;
}

POORSDR_EXPORT size_t poorsdr_fft_adpcm_decode(
    const uint8_t *input, size_t input_size, int16_t *output, size_t output_size
) {
    size_t i;
    size_t needed = input_size * 2U;
    int step_index = 0;
    int predictor = 0;
    int step = 0;
    if (!input || !output || output_size < needed) return 0;
    for (i = 0; i < input_size; ++i) {
        output[i * 2U] = decode_nibble(input[i] & 15U, &step_index, &predictor, &step);
        output[i * 2U + 1U] = decode_nibble(input[i] >> 4U, &step_index, &predictor, &step);
    }
    return needed;
}
