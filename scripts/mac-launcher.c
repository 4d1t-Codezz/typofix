/* The Mac app's main executable. It runs Python inside this process instead of starting a separate
 * python3 binary, so macOS sees "Typofix" as the app asking for Accessibility access. A script
 * launcher would pass that request to python3, and switching Typofix on in System Settings would
 * then do nothing.
 *
 * The Python code lives in ~/Library/Application Support/Typofix/app, not in the bundle. macOS ties
 * the Accessibility permission to the exact bundle (its code signature), so keeping the bundle the
 * same from one version to the next means updating Typofix doesn't lose the permission.
 *
 * build-mac-app.sh compiles this with LIBPYTHON (the Python shared library) and PYTHONHOME_DIR
 * (that Python's sys.base_prefix) baked in. */

#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) {
        fprintf(stderr, "Typofix: can't find its own location\n");
        return 1;
    }
    /* real is .../Typofix.app/Contents/MacOS/Typofix. */
    char *slash = strrchr(real, '/');
    if (!slash) return 1;
    *slash = '\0';
    const char *home = getenv("HOME");
    if (!home) return 1;
    char app_dir[PATH_MAX], bundle[PATH_MAX], bundle_real[PATH_MAX];
    snprintf(app_dir, sizeof app_dir, "%s/Library/Application Support/Typofix/app", home);
    snprintf(bundle, sizeof bundle, "%s/../..", real);
    if (chdir(app_dir) != 0) {
        fprintf(stderr, "Typofix: can't open %s\n", app_dir);
        return 1;
    }
    if (realpath(bundle, bundle_real)) setenv("TYPOFIX_APP", bundle_real, 1);  /* for "open at login" */

    setenv("PYTHONHOME", PYTHONHOME_DIR, 1);
    void *lib = dlopen(LIBPYTHON, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) {
        fprintf(stderr, "Typofix: can't load Python (%s). Reinstall it with Install on Mac.command.\n",
                dlerror());
        return 1;
    }
    int (*py_main)(int, char **) = (int (*)(int, char **))dlsym(lib, "Py_BytesMain");
    if (!py_main) {
        fprintf(stderr, "Typofix: %s\n", dlerror());
        return 1;
    }
    /* Pass our own arguments along (the login item adds --background). */
    char *args[16] = {argv[0], "-m", "typofix"};
    int n = 3;
    for (int i = 1; i < argc && n < 15; i++) args[n++] = argv[i];
    args[n] = NULL;
    return py_main(n, args);
}
