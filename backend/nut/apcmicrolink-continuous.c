/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#include "apcmicrolink-continuous.h"

#include <locale.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __APPLE__
#include <xlocale.h>
#endif

static const mlink_continuous_kind_t expected_kinds[MLINK_CONTINUOUS_FIELD_COUNT] = {
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_REPORTED, MLINK_CONTINUOUS_STATIC,
	MLINK_CONTINUOUS_STATIC, MLINK_CONTINUOUS_DRIVER_DERIVED,
	MLINK_CONTINUOUS_DRIVER_DERIVED
};

static const char *const field_names[MLINK_CONTINUOUS_FIELD_COUNT] = {
	"ups.status", "battery.charge", "battery.runtime", "battery.voltage",
	"battery.temperature", "ups.temperature", "input.voltage",
	"input.frequency", "output.voltage", "output.current",
	"output.frequency", "ups.load", "experimental.ups.load.apparent",
	"ups.realpower.nominal", "ups.power.nominal", "ups.realpower", "ups.power"
};

static const char *kind_name(mlink_continuous_kind_t kind)
{
	switch (kind) {
	case MLINK_CONTINUOUS_REPORTED: return "reported";
	case MLINK_CONTINUOUS_DRIVER_DERIVED: return "driverDerived";
	case MLINK_CONTINUOUS_STATIC: return "static";
	default: return NULL;
	}
}

static const char *state_name(mlink_continuous_state_t state)
{
	switch (state) {
	case MLINK_CONTINUOUS_OBSERVED: return "observed";
	case MLINK_CONTINUOUS_UNAVAILABLE: return "unavailable";
	case MLINK_CONTINUOUS_INVALID: return "invalid";
	default: return NULL;
	}
}

void mlink_continuous_fields_clear(mlink_continuous_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT])
{
	size_t i;
	for (i = 0; i < MLINK_CONTINUOUS_FIELD_COUNT; i++) {
		memset(&fields[i], 0, sizeof(fields[i]));
		fields[i].state = MLINK_CONTINUOUS_UNAVAILABLE;
		fields[i].kind = expected_kinds[i];
	}
}

int mlink_continuous_number_valid(const char *value)
{
	const unsigned char *p = (const unsigned char *)value;
	locale_t c_locale;
	char *end = NULL;
	double parsed;
	int valid;
	if (p == NULL || *p == '\0' || strlen(value) > MLINK_CONTINUOUS_MAX_VALUE)
		return 0;
	if (*p == '-') p++;
	if (*p == '0') {
		p++;
		if (*p >= '0' && *p <= '9') return 0;
	} else {
		if (*p < '1' || *p > '9') return 0;
		while (*p >= '0' && *p <= '9') p++;
	}
	if (*p == '.') {
		p++;
		if (*p < '0' || *p > '9') return 0;
		while (*p >= '0' && *p <= '9') p++;
	}
	if (*p == 'e' || *p == 'E') {
		unsigned int exponent_digits = 0;
		p++;
		if (*p == '+' || *p == '-') p++;
		while (*p >= '0' && *p <= '9') { exponent_digits++; p++; }
		if (exponent_digits == 0) return 0;
	}
	if (*p != '\0') return 0;
	c_locale = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
	if (c_locale == (locale_t)0) return 0;
	parsed = strtod_l(value, &end, c_locale);
	valid = end != value && *end == '\0' && isfinite(parsed);
	freelocale(c_locale);
	return valid;
}

static int token_allowed(const char *token, size_t len)
{
	static const char *const tokens[] = {
		"ALARM", "BOOST", "BYPASS", "CAL", "FSD", "HB", "LB", "OB",
		"OFF", "OL", "OVER", "RB", "TRIM"
	};
	size_t i;
	for (i = 0; i < sizeof(tokens) / sizeof(tokens[0]); i++) {
		if (strlen(tokens[i]) == len && memcmp(tokens[i], token, len) == 0)
			return 1;
	}
	return 0;
}

int mlink_continuous_status_valid(const char *value)
{
	const char *p = value;
	const char *previous = NULL;
	size_t previous_len = 0;
	int saw_ol = 0, saw_ob = 0;
	if (p == NULL || *p == '\0' || strlen(p) > 128U)
		return 0;
	while (*p != '\0') {
		const char *start = p;
		size_t len;
		while (*p != '\0' && *p != ' ') {
			if ((unsigned char)*p < 0x21U || (unsigned char)*p > 0x7eU)
				return 0;
			p++;
		}
		len = (size_t)(p - start);
		if (len == 0 || !token_allowed(start, len)) return 0;
		if (previous != NULL) {
			int order = memcmp(previous, start,
				previous_len < len ? previous_len : len);
			if (order > 0 || (order == 0 && previous_len >= len)) return 0;
		}
		if (len == 2 && memcmp(start, "OL", 2) == 0) saw_ol = 1;
		if (len == 2 && memcmp(start, "OB", 2) == 0) saw_ob = 1;
		previous = start;
		previous_len = len;
		if (*p == ' ') {
			p++;
			if (*p == '\0' || *p == ' ') return 0;
		}
	}
	return !(saw_ol && saw_ob);
}

static int value_valid(const char *value, size_t field_index)
{
	return field_index == 0U
		? mlink_continuous_status_valid(value)
		: mlink_continuous_number_valid(value);
}

int mlink_continuous_field_observed(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind, const char *value, uint32_t observed_ms)
{
	if (field == NULL || value == NULL || kind_name(kind) == NULL
	 || strlen(value) >= sizeof(field->value))
		return 0;
	strcpy(field->value, value);
	field->observed_ms = observed_ms;
	field->kind = kind;
	field->state = MLINK_CONTINUOUS_OBSERVED;
	field->has_value = 1;
	field->has_time = 1;
	return 1;
}

void mlink_continuous_field_unavailable(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind)
{
	if (field == NULL) return;
	memset(field, 0, sizeof(*field));
	field->kind = kind;
	field->state = MLINK_CONTINUOUS_UNAVAILABLE;
}

void mlink_continuous_field_invalid(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind)
{
	if (field == NULL) return;
	memset(field, 0, sizeof(*field));
	field->kind = kind;
	field->state = MLINK_CONTINUOUS_INVALID;
}

void mlink_continuous_field_mirror(mlink_continuous_field_t *destination,
	const mlink_continuous_field_t *source)
{
	if (destination == NULL || source == NULL) return;
	*destination = *source;
}

int mlink_continuous_page_dependency(const mlink_continuous_page_t *pages,
	size_t page_count, size_t width, size_t blob_len, size_t offset,
	size_t size, uint64_t *oldest_ms)
{
	size_t end, first, last, page;
	uint64_t oldest = UINT64_MAX;
	if (pages == NULL || oldest_ms == NULL || width == 0 || size == 0
	 || offset > blob_len || size > blob_len - offset)
		return 0;
	end = offset + size;
	first = offset / width;
	last = (end - 1U) / width;
	if (last >= page_count) return 0;
	for (page = first; page <= last; page++) {
		size_t page_start = page * width;
		size_t required = end - page_start < width ? end - page_start : width;
		if (!pages[page].received_valid || !pages[page].copied_valid
		 || pages[page].copied_len < required)
			return 0;
		if (pages[page].received_ms < oldest) oldest = pages[page].received_ms;
	}
	if (oldest == UINT64_MAX) return 0;
	*oldest_ms = oldest;
	return 1;
}

int mlink_continuous_definition_unchanged(const unsigned char *admitted,
	size_t admitted_len, const unsigned char *current, size_t current_len,
	size_t begin, size_t end)
{
	if (admitted == NULL || current == NULL || begin > end
	 || end > admitted_len || end > current_len)
		return 0;
	return memcmp(admitted + begin, current + begin, end - begin) == 0;
}

int mlink_continuous_definition_range_valid(size_t data_ptr_offset,
	size_t parsed_end, size_t blob_len, size_t max_definition_len)
{
	return data_ptr_offset > 12U && data_ptr_offset <= blob_len
		&& parsed_end >= 12U && parsed_end <= data_ptr_offset
		&& data_ptr_offset - 12U <= max_definition_len;
}

static const char *reason_name(mlink_continuous_end_reason_t reason)
{
	switch (reason) {
	case MLINK_CONTINUOUS_END_DURATION_COMPLETE: return "duration_complete";
	case MLINK_CONTINUOUS_END_CANCELLED: return "cancelled";
	case MLINK_CONTINUOUS_END_DEVICE_LOST: return "device_lost";
	case MLINK_CONTINUOUS_END_SESSION_LOST: return "session_lost";
	case MLINK_CONTINUOUS_END_GUARD_ERROR: return "guard_error";
	case MLINK_CONTINUOUS_END_OUTPUT_ERROR: return "output_error";
	default: return NULL;
	}
}

int mlink_continuous_sample_line(char *out, size_t out_size,
	uint32_t sequence, uint32_t slot, uint32_t elapsed_ms,
	uint32_t missed_slots,
	const mlink_continuous_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT])
{
	size_t used = 0, i;
	int n;
	if (out == NULL || fields == NULL || out_size == 0 || sequence < 1U
	 || sequence > 24U || slot > 23U || elapsed_ms > 119999U
	 || slot != elapsed_ms / 5000U
	 || slot + 1U < sequence || missed_slots != slot + 1U - sequence
	 || missed_slots > 23U)
		return 0;
	n = snprintf(out, out_size,
		"{\"protocol\":\"ups-monitor.continuous.v1\",\"schema_version\":1,\"type\":\"sample\",\"sequence\":%u,\"slot\":%u,\"elapsed_ms\":%u,\"missed_slots\":%u,\"fields\":{",
		sequence, slot, elapsed_ms, missed_slots);
	if (n < 0 || (size_t)n >= out_size) return 0;
	used = (size_t)n;
	for (i = 0; i < MLINK_CONTINUOUS_FIELD_COUNT; i++) {
		const mlink_continuous_field_t *field = &fields[i];
		const char *kind = kind_name(field->kind);
		const char *state = state_name(field->state);
		char observed[16];
		if (kind == NULL || state == NULL) return 0;
		if (field->kind != expected_kinds[i]) return 0;
		if ((field->state == MLINK_CONTINUOUS_OBSERVED) != (field->has_value && field->has_time)) return 0;
		if (field->state != MLINK_CONTINUOUS_OBSERVED && (field->has_value || field->has_time)) return 0;
		if (field->state == MLINK_CONTINUOUS_OBSERVED
		 && (field->observed_ms > elapsed_ms || !value_valid(field->value, i))) return 0;
		if (field->has_time) {
			snprintf(observed, sizeof(observed), "%u", field->observed_ms);
		} else {
			strcpy(observed, "null");
		}
		n = snprintf(out + used, out_size - used,
			"%s\"%s\":{\"value\":%s%s%s,\"observed_ms\":%s,\"kind\":\"%s\",\"state\":\"%s\"}",
			i == 0 ? "" : ",", field_names[i],
			field->has_value ? "\"" : "", field->has_value ? field->value : "null",
			field->has_value ? "\"" : "", observed, kind, state);
		if (n < 0 || (size_t)n >= out_size - used) return 0;
		used += (size_t)n;
	}
	n = snprintf(out + used, out_size - used, "}}\n");
	if (n < 0 || (size_t)n >= out_size - used) return 0;
	used += (size_t)n;
	return used <= MLINK_CONTINUOUS_MAX_LINE;
}

int mlink_continuous_end_line(char *out, size_t out_size,
	uint32_t elapsed_ms, mlink_continuous_end_reason_t reason)
{
	const char *name = reason_name(reason);
	int n;
	if (out == NULL || out_size == 0 || elapsed_ms > 132000U || name == NULL)
		return 0;
	n = snprintf(out, out_size,
		"{\"protocol\":\"ups-monitor.continuous.v1\",\"schema_version\":1,\"type\":\"end\",\"elapsed_ms\":%u,\"reason\":\"%s\"}\n",
		elapsed_ms, name);
	return n >= 0 && (size_t)n < out_size && (size_t)n <= MLINK_CONTINUOUS_MAX_LINE;
}
