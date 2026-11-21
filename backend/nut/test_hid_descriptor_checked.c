/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "apcmicrolink-hid-descriptor-checked.h"

#include <stdio.h>
#include <string.h>

#define CHECK(expr) do { if (!(expr)) { \
	fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)

typedef struct fixture {
	uint8_t bytes[MLINK_HID_DESC_MAX_BYTES + 1U];
	size_t length;
} fixture_t;

static void put_item(fixture_t *f, unsigned int type, unsigned int tag,
	unsigned int size, uint32_t value)
{
	unsigned int i, code = size == 4U ? 3U : size;
	f->bytes[f->length++] = (uint8_t)((tag << 4) | (type << 2) | code);
	for (i = 0; i < size; i++) f->bytes[f->length++] = (uint8_t)(value >> (8U * i));
}

static void put_usage_page(fixture_t *f, uint32_t page)
{
	put_item(f, 1U, 0U, 2U, page);
}

static void put_target_attr(fixture_t *f, uint8_t report_id, unsigned int usage,
	unsigned int type, uint32_t size, uint32_t count, uint32_t attributes,
	unsigned int attributes_size)
{
	put_item(f, 1U, 8U, 1U, report_id);
	put_usage_page(f, 0xff86U);
	put_item(f, 2U, 0U, 1U, usage);
	put_item(f, 1U, 7U, size <= 255U ? 1U : 4U, size);
	put_item(f, 1U, 9U, count <= 255U ? 1U : 4U, count);
	put_item(f, 0U, type, attributes_size, attributes);
}

static void put_target(fixture_t *f, uint8_t report_id, unsigned int usage,
	unsigned int type, uint32_t size, uint32_t count, uint8_t attributes)
{
	put_target_attr(f, report_id, usage, type, size, count, attributes, 1U);
}

static void put_pair(fixture_t *f)
{
	put_target(f, 7U, 0xfdU, 8U, 8U, 63U, 2U);
	put_target(f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
}

static mlink_hid_desc_status_t parse(fixture_t *f, mlink_hid_desc_result_t *r)
{
	return mlink_hid_desc_parse_checked(f->bytes, f->length, r);
}

static int result_is_zero_except_status(const mlink_hid_desc_result_t *r,
	mlink_hid_desc_status_t status)
{
	mlink_hid_desc_result_t zero;
	memset(&zero, 0, sizeof(zero));
	return r->status == status && r->main_count == 0U
		&& r->input_report_id == 0U && r->output_report_id == 0U
		&& r->input_report_length == 0U && r->output_report_length == 0U
		&& memcmp(r->mains, zero.mains, sizeof(r->mains)) == 0
		&& memcmp(r->total_bits, zero.total_bits, sizeof(r->total_bits)) == 0;
}

static int test_positive_and_foreign_report_counts(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	unsigned int counts[] = {31U, 32U, 33U, 63U};
	size_t i;
	memset(&f, 0, sizeof(f));
	put_pair(&f);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.input_report_id == 7U && r.output_report_id == 7U);
	CHECK(r.input_report_length == 64U && r.output_report_length == 64U);
	CHECK(r.main_count == 2U);
	CHECK(r.mains[0].usage == 0xff8600fdU && r.mains[0].bit_offset == 0U);
	CHECK(r.mains[0].bit_size == 8U && r.mains[0].count == 63U);
	CHECK(r.mains[0].attributes == 2U && r.mains[0].type == MLINK_HID_REPORT_INPUT);
	CHECK(r.total_bits[7][0] == 504U && r.total_bits[7][1] == 504U);
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x0102U, 2U);
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.mains[0].attributes == 0x0102U);
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x00000102U, 4U);
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.mains[0].attributes == 0x00000102U);
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x0101U, 2U);
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f));
	put_pair(&f);
	put_item(&f, 1U, 8U, 1U, 3U); put_usage_page(&f, 1U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 1U, 7U, 1U, 8U);
	put_item(&f, 1U, 9U, 1U, 31U); put_item(&f, 0U, 11U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.total_bits[3][2] == 248U);
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_item(&f, 2U, 0U, 4U, 0xff8600fdU);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 8U, 1U, 2U); put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.mains[0].usage == 0xff8600fdU);
	for (i = 0; i < sizeof(counts)/sizeof(counts[0]); i++) {
		memset(&f, 0, sizeof(f));
		put_item(&f, 1U, 8U, 1U, 2U);
		put_usage_page(&f, 1U);
		put_item(&f, 2U, 0U, 1U, 1U);
		put_item(&f, 1U, 7U, 1U, 8U);
		put_item(&f, 1U, 9U, 1U, counts[i]);
		put_item(&f, 0U, 8U, 1U, 2U);
		put_pair(&f);
		CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
		CHECK(r.total_bits[2][0] == counts[i] * 8U);
	}
	return 0;
}

static int test_structural_rejections(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	memset(&f, 0, sizeof(f));
	put_pair(&f); f.bytes[f.length++] = 0x76U;
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	CHECK(r.error_offset == f.length - 1U);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_MALFORMED));

	memset(&f, 0, sizeof(f)); f.bytes[f.length++] = 0xfeU;
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f)); put_item(&f, 1U, 10U, 0U, 0U); /* Push */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f)); put_item(&f, 1U, 11U, 0U, 0U); /* Pop */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 1U, 1U, 1U); /* Usage Minimum */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 2U, 1U, 1U); /* Usage Maximum */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 10U, 1U, 1U); /* Delimiter */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); f.bytes[f.length++] = 0x0cU; /* Reserved type */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 0U, 13U, 0U, 0U); /* unknown Main tag */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 0U, 12U, 0U, 0U); /* unmatched end */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_MALFORMED));
	memset(&f, 0, sizeof(f)); put_item(&f, 1U, 8U, 1U, 0U); /* explicit ID 0 */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	memset(&f, 0, sizeof(f)); put_item(&f, 1U, 8U, 2U, 256U); /* invalid ID width/value */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	memset(&f, 0, sizeof(f)); put_pair(&f);
	put_item(&f, 1U, 7U, 1U, 0U); put_item(&f, 1U, 9U, 1U, 1U);
	put_item(&f, 0U, 8U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_MALFORMED));
	memset(&f, 0, sizeof(f)); put_pair(&f);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 0U);
	put_item(&f, 0U, 8U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	memset(&f, 0, sizeof(f)); put_pair(&f); f.length = MLINK_HID_DESC_MAX_BYTES + 1U;
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_LIMIT));
	return 0;
}

static int test_string_index_is_ignored_locally(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t expected, actual;
	unsigned int width;
	memset(&f, 0, sizeof(f)); put_pair(&f);
	CHECK(parse(&f, &expected) == MLINK_HID_DESC_OK);
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	put_item(&f, 2U, 7U, 1U, 0U); /* String Index before Usage. */
	put_item(&f, 2U, 0U, 1U, 0xfdU);
	put_item(&f, 2U, 7U, 2U, 0x1234U); /* Repeated, interleaved String Index. */
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 8U, 1U, 2U);
	put_usage_page(&f, 0xff86U); put_item(&f, 2U, 7U, 4U, 0U);
	put_item(&f, 2U, 0U, 1U, 0xfcU);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 9U, 1U, 2U);
	CHECK(parse(&f, &actual) == MLINK_HID_DESC_OK);
	CHECK(actual.main_count == expected.main_count);
	CHECK(memcmp(actual.mains, expected.mains, sizeof(actual.mains)) == 0);
	CHECK(memcmp(actual.total_bits, expected.total_bits, sizeof(actual.total_bits)) == 0);
	CHECK(actual.input_report_id == expected.input_report_id
		&& actual.output_report_id == expected.output_report_id
		&& actual.input_report_length == expected.input_report_length
		&& actual.output_report_length == expected.output_report_length);
	for (width = 1U; width <= 4U; width++) {
		unsigned int code;
		if (width == 3U) continue;
		code = width == 4U ? 3U : width;
		memset(&f, 0, sizeof(f)); f.bytes[f.length++] = (uint8_t)((7U << 4) | (2U << 2) | code);
		CHECK(parse(&f, &actual) == MLINK_HID_DESC_MALFORMED); /* truncated payload */
		CHECK(result_is_zero_except_status(&actual, MLINK_HID_DESC_MALFORMED));
	}
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 7U, 0U, 0U);
	CHECK(parse(&f, &actual) == MLINK_HID_DESC_MALFORMED); /* zero-width index */
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 8U, 1U, 1U); /* String Minimum */
	CHECK(parse(&f, &actual) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_item(&f, 2U, 9U, 1U, 1U); /* String Maximum */
	CHECK(parse(&f, &actual) == MLINK_HID_DESC_UNSUPPORTED);
	return 0;
}

static int test_tunnel_shape_and_ambiguity(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	memset(&f, 0, sizeof(f));
	put_target(&f, 7U, 0xfdU, 8U, 504U, 1U, 2U);
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f));
	put_target(&f, 7U, 0xfdU, 9U, 8U, 63U, 2U);
	put_target(&f, 7U, 0xfcU, 8U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f));
	put_target(&f, 7U, 0xfdU, 11U, 8U, 63U, 2U);
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	memset(&f, 0, sizeof(f)); put_pair(&f); put_target(&f, 9U, 0xfdU, 8U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_AMBIGUOUS);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_AMBIGUOUS));
	memset(&f, 0, sizeof(f)); put_pair(&f); put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_AMBIGUOUS);
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	put_item(&f, 2U, 0U, 1U, 0xfdU); put_item(&f, 2U, 0U, 1U, 1U);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 8U, 1U, 2U); put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_AMBIGUOUS);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_AMBIGUOUS));
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 2U, 0U, 1U, 0xfdU);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 8U, 1U, 2U); put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_AMBIGUOUS);
	memset(&f, 0, sizeof(f)); put_target(&f, 7U, 0xfdU, 8U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_NO_TUNNEL);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_NO_TUNNEL));
	memset(&f, 0, sizeof(f)); put_target(&f, 0U, 0xfdU, 8U, 8U, 63U, 2U);
	put_target(&f, 0U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_MALFORMED);
	memset(&f, 0, sizeof(f));
	put_usage_page(&f, 0xff86U); put_item(&f, 2U, 0U, 1U, 0xfdU);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 8U, 1U, 2U);
	put_usage_page(&f, 0xff86U); put_item(&f, 2U, 0U, 1U, 0xfcU);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
	put_item(&f, 0U, 9U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED); /* implicit ID zero */
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	return 0;
}

static int test_padding_offsets_and_totals(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 1U, 7U, 1U, 8U);
	put_item(&f, 1U, 9U, 1U, 1U); put_item(&f, 0U, 8U, 1U, 1U); /* Constant prefix */
	put_pair(&f);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f));
	put_pair(&f);
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 1U, 7U, 1U, 8U);
	put_item(&f, 1U, 9U, 1U, 1U); put_item(&f, 0U, 8U, 1U, 1U); /* Constant suffix */
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	return 0;
}

static int test_collection_and_local_limits(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	unsigned int i;
	memset(&f, 0, sizeof(f));
	for (i = 0; i < 10U; i++) { put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 0U, 10U, 1U, 1U); }
	put_pair(&f);
	for (i = 0; i < 10U; i++) put_item(&f, 0U, 12U, 0U, 0U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	memset(&f, 0, sizeof(f));
	for (i = 0; i < 11U; i++) { put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 0U, 10U, 1U, 1U); }
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_LIMIT));
	memset(&f, 0, sizeof(f));
	put_pair(&f);
	put_item(&f, 1U, 8U, 1U, 9U); put_usage_page(&f, 1U);
	for (i = 0; i < 64U; i++) put_item(&f, 2U, 0U, 1U, i + 1U);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 1U);
	put_item(&f, 0U, 8U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.main_count == 3U && r.mains[0].usage == 0xff8600fdU);
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
	for (i = 0; i < 65U; i++) put_item(&f, 2U, 0U, 1U, i == 0U ? 0xfdU : 1U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	return 0;
}

static int test_report_and_descriptor_limits(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	unsigned int i;
	memset(&f, 0, sizeof(f)); put_pair(&f);
	put_item(&f, 1U, 8U, 1U, 9U);
	for (i = 0; i < 498U; i++) {
		put_usage_page(&f, 1U); put_item(&f, 2U, 0U, 1U, 1U);
		put_item(&f, 1U, 7U, 1U, 1U); put_item(&f, 1U, 9U, 1U, 1U);
		put_item(&f, 0U, 8U, 1U, 2U);
	}
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK && r.main_count == 500U);
	put_usage_page(&f, 1U); put_item(&f, 2U, 0U, 1U, 1U);
	put_item(&f, 1U, 7U, 1U, 1U); put_item(&f, 1U, 9U, 1U, 1U);
	put_item(&f, 0U, 8U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_LIMIT));
	memset(&f, 0, sizeof(f)); put_pair(&f);
	while (f.length + 2U <= MLINK_HID_DESC_MAX_BYTES) put_item(&f, 1U, 1U, 1U, 0U);
	CHECK(f.length == MLINK_HID_DESC_MAX_BYTES);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	f.bytes[f.length++] = 0x00U;
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	return 0;
}

static int test_checked_arithmetic_and_empty_input(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 2U); put_usage_page(&f, 1U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 1U, 7U, 4U, 65536U);
	put_item(&f, 1U, 9U, 1U, 1U); put_item(&f, 0U, 8U, 1U, 2U); put_pair(&f);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.total_bits[2][0] == 65536U && r.main_count == 3U);
	memset(&f, 0, sizeof(f));
	put_item(&f, 1U, 8U, 1U, 2U); put_usage_page(&f, 1U);
	put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 1U, 7U, 4U, 65536U);
	put_item(&f, 1U, 9U, 1U, 1U); put_item(&f, 0U, 8U, 1U, 2U);
	put_item(&f, 1U, 9U, 1U, 1U); put_item(&f, 0U, 8U, 1U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_LIMIT);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_LIMIT));
	memset(&r, 0xa5, sizeof(r));
	CHECK(mlink_hid_desc_parse_checked(NULL, 0U, &r) == MLINK_HID_DESC_MALFORMED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_MALFORMED));
	return 0;
}

static int test_attribute_and_numbered_report_policy(void)
{
	static fixture_t f;
	static mlink_hid_desc_result_t r;
	unsigned int tag, bit;
	for (tag = 8U; tag <= 11U; tag++) {
		if (tag == 10U) continue;
		for (bit = tag == 8U ? 7U : 9U; bit < 32U; bit++) {
			if (tag == 8U && bit == 7U) continue; /* non-tunnel Input exception below */
			if (bit == 8U) continue;
			memset(&f, 0, sizeof(f));
			put_pair(&f);
			/* Unsupported attributes must also reject unrelated reports. */
			put_target_attr(&f, 9U, 0x20U, tag, 8U, 1U,
				2U | (UINT32_C(1) << bit), 4U);
			CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
			CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
		}
	}
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x12345602U, 4U);
	put_target(&f, 8U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x0102U, 4U);
	put_target_attr(&f, 8U, 0xfcU, 9U, 8U, 63U, 0x0182U, 4U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.mains[1].attributes == 0x0182U);
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 3U, 1U, 8U, 8U, 1U, 0x0082U, 2U); /* Foreign Input data. */
	put_target_attr(&f, 4U, 2U, 8U, 8U, 1U, 0x0081U, 2U); /* Foreign constant Input. */
	put_pair(&f);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_OK);
	CHECK(r.mains[0].attributes == 0x0082U && r.mains[1].attributes == 0x0081U);
	memset(&f, 0, sizeof(f));
	put_target_attr(&f, 7U, 0xfdU, 8U, 8U, 63U, 0x0082U, 2U); /* Tunnel Input. */
	put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	{
		unsigned int order;
		for (order = 0U; order < 2U; order++) {
			memset(&f, 0, sizeof(f));
			if (order == 0U) put_target_attr(&f, 7U, 1U, 8U, 8U, 1U, 0x0082U, 2U);
			put_pair(&f);
			if (order == 1U) put_target_attr(&f, 7U, 1U, 8U, 8U, 1U, 0x0082U, 2U);
			CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
			CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
		}
	}
	{
		unsigned int reverse;
		for (reverse = 0U; reverse < 2U; reverse++) {
			memset(&f, 0, sizeof(f));
			put_item(&f, 1U, 8U, 1U, 7U); put_usage_page(&f, 0xff86U);
			if (reverse == 0U) {
				put_item(&f, 2U, 0U, 1U, 0xfdU); put_item(&f, 2U, 0U, 1U, 1U);
			} else {
				put_item(&f, 2U, 0U, 1U, 1U); put_item(&f, 2U, 0U, 1U, 0xfdU);
			}
			put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 63U);
			put_item(&f, 0U, 8U, 1U, 0x82U); /* Bit 7 remains forbidden with tunnel usage. */
			put_target(&f, 7U, 0xfcU, 9U, 8U, 63U, 2U);
			CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
			CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
		}
	}
	memset(&f, 0, sizeof(f));
	put_usage_page(&f, 1U); put_item(&f, 2U, 0U, 1U, 1U);
	put_item(&f, 1U, 7U, 1U, 8U); put_item(&f, 1U, 9U, 1U, 64U);
	put_item(&f, 0U, 8U, 1U, 2U); /* Unnumbered report before tunnel. */
	put_pair(&f);
	CHECK(parse(&f, &r) == MLINK_HID_DESC_UNSUPPORTED);
	CHECK(result_is_zero_except_status(&r, MLINK_HID_DESC_UNSUPPORTED));
	return 0;
}

int main(void)
{
	int (*tests[])(void) = {
		test_positive_and_foreign_report_counts,
		test_structural_rejections,
		test_string_index_is_ignored_locally,
		test_tunnel_shape_and_ambiguity,
		test_padding_offsets_and_totals,
		test_collection_and_local_limits,
		test_report_and_descriptor_limits,
		test_checked_arithmetic_and_empty_input,
		test_attribute_and_numbered_report_policy
	};
	size_t i;
	for (i = 0; i < sizeof(tests)/sizeof(tests[0]); i++) if (tests[i]() != 0) return 1;
	puts("PASS checked descriptor synthetic suites=9");
	return 0;
}
