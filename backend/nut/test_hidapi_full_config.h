/* SPDX-License-Identifier: MIT */
#ifndef TEST_HIDAPI_FULL_CONFIG_H
#define TEST_HIDAPI_FULL_CONFIG_H

/* Synthetic macOS test configuration; never a generated NUT config.h. */
#define EXEEXT ""
#define RUN_AS_USER "synthetic-replay-user"
#define RUN_AS_GROUP "synthetic-replay-group"
#define CONFPATH "/__ups_full_fake_unconfigured__/conf"
#define STATEPATH "/__ups_full_fake_unconfigured__/state"
#define PIDPATH "/__ups_full_fake_unconfigured__/pid"
#define LIBDIR "/__ups_full_fake_unconfigured__/lib"
#define LOG_FACILITY LOG_DAEMON
#define CONFIG_FLAGS "synthetic-full-replay-test-only"
#define CC_VERSION "synthetic-test-compiler-metadata"
#define PACKAGE_VERSION "0.0.0-test"
#define NUT_WEBSITE_BASE "https://example.invalid/portable-replay"

#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif

#define HAVE_CLOCK_GETTIME 1
#define HAVE_CLOCK_MONOTONIC 1
#define HAVE_FCNTL_H 1
#define HAVE_FLOAT_H 1
#define HAVE_GMTIME_R 1
#define HAVE_GRP_H 1
#define HAVE_INTTYPES_H 1
#define HAVE_LIMITS_H 1
#define HAVE_LOCALTIME_R 1
#define HAVE_MATH_H 1
#define HAVE_PWD_H 1
#define HAVE_SETEUID 1
#define HAVE_SETENV 1
#define HAVE_SIGNAL_H 1
#define HAVE_STDINT_H 1
#define HAVE_STDARG_H 1
#define HAVE_STDIO_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRINGS_H 1
#define HAVE_STRING_H 1
#define HAVE_STRTOF 1
#define HAVE_PTHREAD 1
#define HAVE_SUSECONDS_T 1
#define HAVE_SYS_SIGNAL_H 1
#define HAVE_SYS_STAT_H 1
#define HAVE_SYS_TIME_H 1
#define HAVE_SYS_TYPES_H 1
#define HAVE_SYS_UN_H 1
#define HAVE_TIME_H 1
#define HAVE_TIMEGM 1
#define HAVE_UNISTD_H 1
#define HAVE_UNSETENV 1
#define HAVE_USECONDS_T 1
#define HAVE_VA_COPY 1
#define HAVE_VA_COPY_VARIANT 1

#define WITH_USB 1
#define WITH_LIBUSB_1_0 1
#define WITH_LIBUSB_0_1 0

#endif /* TEST_HIDAPI_FULL_CONFIG_H */
