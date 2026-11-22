/* SPDX-License-Identifier: GPL-2.0-or-later
 * Checked Microlink descriptor parser, materially derived from NUT's HID
 * tokenizer/state machine. See the header for exact source hashes/origins.
 * Copyright (C) 1998-2003 MGE UPS SYSTEMS, Luc Descotils
 * Copyright (C) 2015 Eaton, Arnaud Quette
 * Copyright (C) 2020-2025 Jim Klimov
 */
#include "apcmicrolink-hid-descriptor-checked.h"

#include <string.h>

#define HID_TYPE_MAIN 0U
#define HID_TYPE_GLOBAL 1U
#define HID_TYPE_LOCAL 2U
#define HID_TYPE_RESERVED 3U
#define HID_PAGE_MICROLINK 0xff86U
#define HID_USAGE_MICROLINK_IN 0xfdU
#define HID_USAGE_MICROLINK_OUT 0xfcU
#define HID_MAIN_CONSTANT 0x01U
/* Conservative admission policy, not a general HID conformance validator. */
#define HID_INPUT_SUPPORTED_ATTRIBUTES 0x017fU
#define HID_OUTPUT_FEATURE_SUPPORTED_ATTRIBUTES 0x01ffU

typedef struct parser_state {
	const uint8_t *bytes;
	size_t length;
	size_t position;
	mlink_hid_desc_result_t parsed;
	uint32_t usage_page;
	uint32_t report_size;
	uint32_t report_count;
	uint8_t report_id;
	uint8_t local_count;
	uint32_t local_usages[MLINK_HID_DESC_MAX_LOCAL_USAGES];
	uint8_t collection_depth;
} parser_state_t;

static uint32_t read_le(const uint8_t *bytes, unsigned int size)
{
	uint32_t value = 0;
	unsigned int i;
	for (i = 0; i < size; i++) value |= (uint32_t)bytes[i] << (8U * i);
	return value;
}

static int valid_scalar_size(unsigned int size)
{
	return size == 0U || size == 1U || size == 2U || size == 4U;
}

static int valid_nonempty_scalar_size(unsigned int size)
{
	return size == 1U || size == 2U || size == 4U;
}

static void reset_local(parser_state_t *state)
{
	state->local_count = 0;
	memset(state->local_usages, 0, sizeof(state->local_usages));
}

static mlink_hid_desc_status_t fail_result(mlink_hid_desc_result_t *result,
	mlink_hid_desc_status_t status, size_t offset)
{
	memset(result, 0, sizeof(*result));
	result->status = status;
	result->error_offset = offset;
	return status;
}

static mlink_hid_desc_status_t add_usage(parser_state_t *state, unsigned int size,
	uint32_t value)
{
	uint32_t usage;
	if (!valid_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
	if (state->local_count >= MLINK_HID_DESC_MAX_LOCAL_USAGES) return MLINK_HID_DESC_LIMIT;
	if (size == 4U) {
		usage = value;
	} else {
		if (state->usage_page > 0xffffU) return MLINK_HID_DESC_LIMIT;
		usage = (state->usage_page << 16) | (value & 0xffffU);
	}
	state->local_usages[state->local_count++] = usage;
	return MLINK_HID_DESC_OK;
}

static int type_index(uint8_t type)
{
	return (int)type - 1;
}

static mlink_hid_desc_status_t add_main(parser_state_t *state, uint8_t type,
	uint32_t attributes)
{
	mlink_hid_main_record_t *record;
	uint64_t bits;
	uint32_t total;
	unsigned int i;
	int has_tunnel_usage = 0;
	int direction = type_index(type);
	uint32_t supported_attributes = type == MLINK_HID_REPORT_INPUT
		? HID_INPUT_SUPPORTED_ATTRIBUTES : HID_OUTPUT_FEATURE_SUPPORTED_ATTRIBUTES;
	if (state->parsed.main_count >= MLINK_HID_DESC_MAX_MAINS) return MLINK_HID_DESC_LIMIT;
	if (direction < 0 || direction > 2 || state->report_size == 0U || state->report_count == 0U) {
		return MLINK_HID_DESC_MALFORMED;
	}
	for (i = 0; i < state->local_count; i++) {
		if (state->local_usages[i] == ((uint32_t)HID_PAGE_MICROLINK << 16 | HID_USAGE_MICROLINK_IN)
		 || state->local_usages[i] == ((uint32_t)HID_PAGE_MICROLINK << 16 | HID_USAGE_MICROLINK_OUT)) {
			has_tunnel_usage = 1;
		}
	}
	/* HID reserves Input bit 7; tolerate it only on unrelated, non-tunnel Input. */
	if (type == MLINK_HID_REPORT_INPUT && !has_tunnel_usage) {
		supported_attributes |= 0x0080U;
	}
	/* Raw input filtering assumes every report starts with a numbered ID. */
	if (state->report_id == 0U || (attributes & ~supported_attributes) != 0U) {
		return MLINK_HID_DESC_UNSUPPORTED;
	}
	if (has_tunnel_usage && state->local_count != 1U) return MLINK_HID_DESC_AMBIGUOUS;
	if ((uint64_t)state->report_count > (uint64_t)MLINK_HID_DESC_MAX_REPORT_BITS / state->report_size) {
		return MLINK_HID_DESC_LIMIT;
	}
	bits = (uint64_t)state->report_size * (uint64_t)state->report_count;
	total = state->parsed.total_bits[state->report_id][direction];
	if (bits > MLINK_HID_DESC_MAX_REPORT_BITS
	 || (uint64_t)total + bits > MLINK_HID_DESC_MAX_REPORT_BITS) {
		return MLINK_HID_DESC_LIMIT;
	}
	if (state->parsed.main_count >= MLINK_HID_DESC_MAX_MAINS) return MLINK_HID_DESC_LIMIT;
	record = &state->parsed.mains[state->parsed.main_count++];
	record->usage = state->local_count ? state->local_usages[0] : 0U;
	record->bit_offset = total;
	record->bit_size = state->report_size;
	record->count = state->report_count;
	record->attributes = attributes;
	record->report_id = state->report_id;
	record->type = type;
	state->parsed.total_bits[state->report_id][direction] = total + (uint32_t)bits;
	reset_local(state);
	return MLINK_HID_DESC_OK;
}

static mlink_hid_desc_status_t parse_item(parser_state_t *state, uint8_t prefix,
	unsigned int size, uint32_t value)
{
	unsigned int type = (prefix >> 2) & 3U;
	unsigned int tag = prefix >> 4;
	if (type == HID_TYPE_MAIN) {
		if (tag == 8U || tag == 9U || tag == 11U) {
			uint8_t report_type = tag == 8U ? MLINK_HID_REPORT_INPUT
				: (tag == 9U ? MLINK_HID_REPORT_OUTPUT : MLINK_HID_REPORT_FEATURE);
			if (!valid_nonempty_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
			return add_main(state, report_type, value);
		}
		if (tag == 10U) {
			if (size != 1U) return MLINK_HID_DESC_MALFORMED;
			if (state->collection_depth >= MLINK_HID_DESC_MAX_COLLECTION_DEPTH) return MLINK_HID_DESC_LIMIT;
			state->collection_depth++;
			reset_local(state);
			return MLINK_HID_DESC_OK;
		}
		if (tag == 12U) {
			if (size != 0U || state->collection_depth == 0U) return MLINK_HID_DESC_MALFORMED;
			state->collection_depth--;
			reset_local(state);
			return MLINK_HID_DESC_OK;
		}
		return MLINK_HID_DESC_UNSUPPORTED;
	}
	if (type == HID_TYPE_GLOBAL) {
		if (tag == 0U) {
			if (!valid_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
			if (value > 0xffffU) return MLINK_HID_DESC_LIMIT;
			state->usage_page = value;
			return MLINK_HID_DESC_OK;
		}
		if (tag >= 1U && tag <= 6U) {
			if (tag == 5U ? size != 1U : !valid_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
			return MLINK_HID_DESC_OK;
		}
		if (tag == 7U) {
			if (!valid_nonempty_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
			if (value == 0U) return MLINK_HID_DESC_MALFORMED;
			if (value > MLINK_HID_DESC_MAX_REPORT_BITS) return MLINK_HID_DESC_LIMIT;
			state->report_size = value;
			return MLINK_HID_DESC_OK;
		}
		if (tag == 8U) {
			if (size != 1U) return MLINK_HID_DESC_MALFORMED;
			if (value == 0U) return MLINK_HID_DESC_MALFORMED;
			state->report_id = (uint8_t)value;
			return MLINK_HID_DESC_OK;
		}
		if (tag == 9U) {
			if (!valid_nonempty_scalar_size(size)) return MLINK_HID_DESC_MALFORMED;
			if (value == 0U) return MLINK_HID_DESC_MALFORMED;
			state->report_count = value;
			return MLINK_HID_DESC_OK;
		}
		/* NUT recognizes Push/Pop but does not preserve a checked stack here. */
		if (tag == 10U || tag == 11U) return MLINK_HID_DESC_UNSUPPORTED;
		return MLINK_HID_DESC_UNSUPPORTED;
	}
	if (type == HID_TYPE_LOCAL) {
		if (tag == 0U) return add_usage(state, size, value);
		/* A String Index is descriptive only; retain no string state or lookup. */
		if (tag == 7U) return valid_nonempty_scalar_size(size)
			? MLINK_HID_DESC_OK : MLINK_HID_DESC_MALFORMED;
		/* UsageMin/Max, Designator/String ranges and Delimiter are unsupported. */
		return MLINK_HID_DESC_UNSUPPORTED;
	}
	return MLINK_HID_DESC_UNSUPPORTED;
}

static mlink_hid_desc_status_t validate_tunnel(mlink_hid_desc_result_t *result,
	size_t length)
{
	size_t i;
	const mlink_hid_main_record_t *input = NULL, *output = NULL;
	unsigned int input_matches = 0, output_matches = 0;
	int wrong_direction = 0;
	for (i = 0; i < result->main_count; i++) {
		const mlink_hid_main_record_t *record = &result->mains[i];
		if (record->usage == (0xff860000U | HID_USAGE_MICROLINK_IN)) {
			if (record->type == MLINK_HID_REPORT_INPUT) { input = record; input_matches++; }
			else wrong_direction = 1;
		}
		if (record->usage == (0xff860000U | HID_USAGE_MICROLINK_OUT)) {
			if (record->type == MLINK_HID_REPORT_OUTPUT) { output = record; output_matches++; }
			else wrong_direction = 1;
		}
	}
	if (input_matches > 1U || output_matches > 1U) {
		result->status = MLINK_HID_DESC_AMBIGUOUS;
		result->error_offset = length;
		return result->status;
	}
	if (wrong_direction) {
		result->status = MLINK_HID_DESC_UNSUPPORTED;
		result->error_offset = length;
		return result->status;
	}
	if (input == NULL || output == NULL) {
		result->status = MLINK_HID_DESC_NO_TUNNEL;
		result->error_offset = length;
		return result->status;
	}
	if ((input->attributes & HID_MAIN_CONSTANT) != 0U
	 || (output->attributes & HID_MAIN_CONSTANT) != 0U
	 || input->report_id == 0U || output->report_id == 0U
	 || input->bit_offset != 0U || output->bit_offset != 0U
	 || input->bit_size != 8U || output->bit_size != 8U
	 || input->count != 63U || output->count != 63U
	 || result->total_bits[input->report_id][0] != 504U
	 || result->total_bits[output->report_id][1] != 504U) {
		result->status = MLINK_HID_DESC_UNSUPPORTED;
		result->error_offset = length;
		return result->status;
	}
	result->input_report_id = input->report_id;
	result->output_report_id = output->report_id;
	result->input_report_length = 1U + (result->total_bits[input->report_id][0] + 7U) / 8U;
	result->output_report_length = 1U + (result->total_bits[output->report_id][1] + 7U) / 8U;
	if (result->input_report_length != 64U || result->output_report_length != 64U) {
		result->input_report_id = result->output_report_id = 0U;
		result->input_report_length = result->output_report_length = 0U;
		result->status = MLINK_HID_DESC_UNSUPPORTED;
		result->error_offset = length;
		return result->status;
	}
	result->status = MLINK_HID_DESC_OK;
	result->error_offset = length;
	return result->status;
}

mlink_hid_desc_status_t mlink_hid_desc_parse_checked(const uint8_t *bytes,
	size_t length, mlink_hid_desc_result_t *result)
{
	parser_state_t state;
	mlink_hid_desc_status_t status;
	if (result == NULL) return MLINK_HID_DESC_MALFORMED;
	memset(result, 0, sizeof(*result));
	if (bytes == NULL || length == 0U) return fail_result(result, MLINK_HID_DESC_MALFORMED, 0U);
	if (length > MLINK_HID_DESC_MAX_BYTES) return fail_result(result, MLINK_HID_DESC_LIMIT, MLINK_HID_DESC_MAX_BYTES);
	memset(&state, 0, sizeof(state));
	state.bytes = bytes;
	state.length = length;
	state.parsed.status = MLINK_HID_DESC_MALFORMED;
	while (state.position < state.length) {
		size_t item_offset = state.position;
		uint8_t prefix = state.bytes[state.position++];
		unsigned int size_code, size;
		uint32_t value;
		if (prefix == 0xfeU) return fail_result(result, MLINK_HID_DESC_UNSUPPORTED, item_offset);
		if (((prefix >> 2) & 3U) == HID_TYPE_RESERVED) return fail_result(result, MLINK_HID_DESC_UNSUPPORTED, item_offset);
		size_code = prefix & 3U;
		size = size_code == 3U ? 4U : size_code;
		if ((size_t)size > state.length - state.position) return fail_result(result, MLINK_HID_DESC_MALFORMED, item_offset);
		value = read_le(state.bytes + state.position, size);
		state.position += size;
		status = parse_item(&state, prefix, size, value);
		if (status != MLINK_HID_DESC_OK) return fail_result(result, status, item_offset);
	}
	if (state.collection_depth != 0U) return fail_result(result, MLINK_HID_DESC_MALFORMED, length);
	state.parsed.status = MLINK_HID_DESC_OK;
	state.parsed.error_offset = length;
	status = validate_tunnel(&state.parsed, length);
	if (status != MLINK_HID_DESC_OK) return fail_result(result, status, length);
	*result = state.parsed;
	return status;
}
