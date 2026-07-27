obj-m += hp-wmi.o

KVERSION ?= $(shell uname -r)
KERNEL_BUILD ?= /lib/modules/$(KVERSION)/build

# When KERNELRELEASE is set we are being re-read by the kernel build system.
# Only obj-m (above) is needed in that context — skip everything else.
ifeq ($(KERNELRELEASE),)

.DEFAULT_GOAL := all

# Check if the kernel was built with clang
ifeq ($(shell grep -q "CONFIG_CC_IS_CLANG=y" $(KERNEL_BUILD)/include/config/auto.conf 2>/dev/null && echo yes),yes)
    MAKE_OPTS += LLVM=1
endif

# ---------------------------------------------------------------------------
# Pre-flight: make sure the kernel build tree is usable.
# ---------------------------------------------------------------------------
.PHONY: check-env
check-env:
	@if [ ! -d "$(KERNEL_BUILD)" ]; then \
		echo ""; \
		echo "ERROR: Kernel build directory not found: $(KERNEL_BUILD)"; \
		echo ""; \
		echo "  Install kernel headers for your running kernel:"; \
		echo "    Debian/Ubuntu : sudo apt install linux-headers-$$(uname -r)"; \
		echo "    Fedora/RHEL   : sudo dnf install kernel-devel-$$(uname -r)"; \
		echo "    Arch Linux    : sudo pacman -S linux-headers"; \
		echo ""; \
		exit 1; \
	fi
	@if [ ! -f "$(KERNEL_BUILD)/scripts/basic/Makefile" ] && [ ! -f "$$(readlink -f $(KERNEL_BUILD))/scripts/basic/Makefile" ]; then \
		echo ""; \
		echo "ERROR: scripts/basic/Makefile not found."; \
		echo ""; \
		echo "  Your kernel build environment is missing kbuild scripts."; \
		if [ -f /etc/debian_version ]; then \
			kbuild_ver=$$(uname -r | cut -d. -f1,2,3 | cut -d+ -f1); \
			echo ""; \
			echo "  Debian/Ubuntu fix:"; \
			echo "    sudo apt install \"linux-kbuild-$$kbuild_ver*\""; \
		else \
			echo ""; \
			echo "  Reinstall your kernel headers/build package."; \
		fi; \
		echo ""; \
		exit 1; \
	fi

# Detect the platform_profile API variant by inspecting the installed kernel
# header and write the result to omen_pp_compat.h for hp-wmi.c to include.
# Using a generated header avoids the ccflags-y+= command-line override pitfall.
# The header may reside under KERNEL_BUILD or in a separate -common package
# (Debian splits kernel headers into arch-specific and common packages).

.PHONY: omen_pp_compat.h
omen_pp_compat.h:
	@PP_HDR=$$(find $(KERNEL_BUILD) /usr/src/linux-headers-* /usr/src/kernels/* \
		-name platform_profile.h -path "*/linux/platform_profile.h" \
		2>/dev/null | head -1); \
	if [ -z "$$PP_HDR" ]; then \
		echo "/* Warning: could not find platform_profile.h */" > $@; \
		echo "#define OMEN_PP_API_NEW" >> $@; \
	elif grep -q "devm_platform_profile_register" "$$PP_HDR" 2>/dev/null; then \
		echo "#define OMEN_PP_API_NEW" > $@; \
		if grep -q "platform_profile_remove(struct device \*dev)" "$$PP_HDR" 2>/dev/null || \
		   grep -q "platform_profile_remove(struct device \*)" "$$PP_HDR" 2>/dev/null; then \
			echo "#define OMEN_PP_REMOVE_TAKES_DEVICE" >> $@; \
		fi \
	elif grep -q "platform_profile_handler" "$$PP_HDR" 2>/dev/null; then \
		echo "#define OMEN_PP_API_HANDLER" > $@; \
	else \
		echo "#define OMEN_PP_API_INTERMEDIATE" > $@; \
	fi
	@echo "  GEN     $@ ($$(cat $@ | tr '\n' ' '))"

all: check-env omen_pp_compat.h
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) $(MAKE_OPTS) modules

clean:
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) $(MAKE_OPTS) clean
	rm -f omen_pp_compat.h

install:
	sudo cp hp-wmi.ko /lib/modules/$(KVERSION)/kernel/drivers/platform/x86/hp/hp-wmi.ko
	sudo depmod -a

endif # ifeq ($(KERNELRELEASE),)
