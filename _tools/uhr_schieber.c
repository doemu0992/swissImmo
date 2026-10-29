/* Uhr-Schieber für den Zeitlauf der CI (SICH-45): setzt die Systemuhr eines Prozesses auf einen
 * anderen Tag, ohne Abhängigkeit und ohne Eingriff in den Code.
 *
 * Bauen:  gcc -shared -fPIC -O2 -o uhr_schieber.so _tools/uhr_schieber.c -ldl
 * Nutzen: LD_PRELOAD=$PWD/uhr_schieber.so FAKE_START=<Epoch-Sekunden> python manage.py test ...
 *
 * FAKE_START  Epoch-Sekunden, ab dem ersten Uhr-Aufruf des Prozesses; danach läuft die Uhr normal weiter.
 * FAKE_SLOW   optional: Teiler für die Laufzeit (2 = die Uhr läuft halb so schnell).
 *
 * Verschoben werden clock_gettime(CLOCK_REALTIME), gettimeofday und time. Die monotone Uhr bleibt
 * unberührt, damit Zeitüberschreitungen und Wartezeiten wie gewohnt arbeiten.
 * Gedacht für Testläufe, nicht für den Betrieb.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <time.h>
#include <sys/time.h>
#include <stdlib.h>

static int init = 0;
static double real0 = 0, base = 0, slow = 1;
static int (*r_cg)(clockid_t, struct timespec *) = 0;
static int (*r_gt)(struct timeval *, void *) = 0;
static time_t (*r_t)(time_t *) = 0;

static void setup(void) {
  if (init) return;
  init = 1;
  r_cg = dlsym(RTLD_NEXT, "clock_gettime");
  r_gt = dlsym(RTLD_NEXT, "gettimeofday");
  r_t = dlsym(RTLD_NEXT, "time");
  struct timespec ts;
  r_cg(CLOCK_REALTIME, &ts);
  real0 = ts.tv_sec + ts.tv_nsec / 1e9;
  char *s = getenv("FAKE_START");
  base = s ? atof(s) : real0;
  char *l = getenv("FAKE_SLOW");
  slow = l ? atof(l) : 1;
  if (slow <= 0) slow = 1;
}

static double fake(double real) { return base + (real - real0) / slow; }

int clock_gettime(clockid_t c, struct timespec *ts) {
  setup();
  int r = r_cg(c, ts);
  if (c == CLOCK_REALTIME || c == CLOCK_REALTIME_COARSE) {
    double f = fake(ts->tv_sec + ts->tv_nsec / 1e9);
    ts->tv_sec = (time_t)f;
    ts->tv_nsec = (long)((f - (time_t)f) * 1e9);
  }
  return r;
}

int gettimeofday(struct timeval *tv, void *tz) {
  setup();
  int r = r_gt(tv, tz);
  if (tv) {
    double f = fake(tv->tv_sec + tv->tv_usec / 1e6);
    tv->tv_sec = (time_t)f;
    tv->tv_usec = (long)((f - (time_t)f) * 1e6);
  }
  return r;
}

time_t time(time_t *t) {
  setup();
  time_t r = (time_t)fake((double)r_t(0));
  if (t) *t = r;
  return r;
}
