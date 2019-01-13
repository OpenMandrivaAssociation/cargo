# (akien) This package is (for now) synced with Fedora / Josh Stone's spec.
# The aim is to work with them on a rust packaging policy we could share,
# so that we can ensure a good packaging and share the workload.

%define _disable_ld_no_undefined 1
%define _disable_lto 1

# Only x86_64 and i686 are Tier 1 platforms at this time.
# https://forge.rust-lang.org/platform-support.html
%global rust_arches x86_64 %ix86 armv7hl aarch64

# Only the specified arches will use bootstrap binaries.
#global bootstrap_arches %%{rust_arches}

%if 1
%bcond_with bundled_libgit2
%else
%bcond_with bundled_libgit2
%endif

# (tpg) accordig to Rust devs a LLVM-5.0.0 is not yet supported
%bcond_with llvm

Name:		cargo
Version:	0.32.0
Release:	1
Summary:	Rust's package manager and build tool
Group:		Development/Other
License:	ASL 2.0 or MIT
URL:		https://crates.io/

%global cargo_version %{version}
%global cargo_bootstrap 0.20.0

Source0:	https://github.com/rust-lang/%{name}/archive/%{cargo_version}/%{name}-%{cargo_version}.tar.gz

# Get the Rust triple for any arch.
%{lua: function rust_triple(arch)
  local abi = "gnu"
  if arch == "armv7hl" then
    arch = "armv7"
    abi = "gnueabihf"
  elseif arch == "ppc64" then
    arch = "powerpc64"
  elseif arch == "ppc64le" then
    arch = "powerpc64le"
  elseif arch == "i586" then
    arch = "i686"
  end
  return arch.."-unknown-linux-"..abi
end}

%global rust_triple %{lua: print(rust_triple(rpm.expand("%{_target_cpu}")))}

%if %defined bootstrap_arches
# For each bootstrap arch, add an additional binary Source.
# Also define bootstrap_source just for the current target.
%{lua: do
  local bootstrap_arches = {}
  for arch in string.gmatch(rpm.expand("%{bootstrap_arches}"), "%S+") do
    table.insert(bootstrap_arches, arch)
  end
  local base = rpm.expand("https://static.rust-lang.org/dist/cargo-%{cargo_bootstrap}")
  local target_arch = rpm.expand("%{_target_cpu}")
  for i, arch in ipairs(bootstrap_arches) do
    i = i + 10
    print(string.format("Source%d: %s-%s.tar.xz\n",
                        i, base, rust_triple(arch)))
    if arch == target_arch then
      rpm.define("bootstrap_source "..i)
    end
  end
end}
%endif

# Use vendored crate dependencies so we can build offline.
# Created using https://github.com/alexcrichton/cargo-vendor/ 0.1.14
# It's so big because some of the -sys crates include the C library source they
# want to link to.  With our -devel buildreqs in place, they'll be used instead.
# FIXME: These should all eventually be packaged on their own!
#
# cargo install cargo-vendor
# export PATH=~/.cargo/bin:$PATH
# cd cargo-%{version}
# cargo vendor
# tar cJf cargo-%{version}-vendor.tar.xz vendor
Source100:	%{name}-%{version}-vendor.tar.xz
BuildRequires:	rust >= 0.20.0
BuildRequires:	make
BuildRequires:	cmake
%if %{with llvm}
BuildRequires:	llvm-devel
%else
BuildRequires:	gcc
%endif

%ifarch %{bootstrap_arches}
%global bootstrap_root cargo-%{cargo_bootstrap}-%{rust_triple}
%global local_cargo %{_builddir}/%{bootstrap_root}/cargo/bin/cargo
%else
BuildRequires:	%{name} >= 0.13.0
%global local_cargo %{_bindir}/%{name}
%endif

# Indirect dependencies for vendored -sys crates above
BuildRequires:	pkgconfig(libcurl)
BuildRequires:	pkgconfig(libssh2)
BuildRequires:	openssl-devel
BuildRequires:	zlib-devel

%if %with bundled_libgit2
Provides:	bundled(libgit2) = 0.24.0
%else
BuildRequires:	pkgconfig(libgit2) >= 0.24
%endif

# Cargo is not much use without Rust
Requires:	rust

%description
Cargo is a tool that allows Rust projects to declare their various dependencies
and ensure that you'll always get a repeatable build.

%prep
%ifarch %{bootstrap_arches}
%setup -q -n %{bootstrap_root} -T -b %{bootstrap_source}
test -f '%{local_cargo}'
%endif

# cargo sources
%setup -q -n %{name}-%{cargo_version}

# vendored crates
%setup -q -T -D -a 100

%apply_patches

# define the offline registry
%global cargo_home $PWD/.cargo
mkdir -p %{cargo_home}
cat >.cargo/config <<EOF
[source.crates-io]
registry = 'https://github.com/rust-lang/crates.io-index'
replace-with = 'vendored-sources'

[source.vendored-sources]
directory = '$PWD/vendor'
EOF

# This should eventually migrate to distro policy
# Enable optimization, debuginfo, and link hardening.
%global rustflags -Copt-level=3 -Cdebuginfo=2 -Clink-arg=-Wl,-z,relro,-z,now


%build
export CFLAGS="%{optflags}"
export CXXFLAGS="%{optflags}"
export LDFLAGS="%{ldflags}"

%if !%{with llvm}
export CC=gcc
export CXX=g++
# for some reason parts of the code still use cc call rather than the environment
# which results in a mixture
mkdir omv_build_comp
ln -s `which gcc` omv_build_comp/cc
ln -s `which g++` omv_build_comp/g++
export PATH=$PWD/omv_build_comp:$PATH
%endif

%if %without bundled_libgit2
# convince libgit2-sys to use the distro libgit2
export LIBGIT2_SYS_USE_PKG_CONFIG=1
%endif

# use our offline registry and custom rustc flags
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"

%{local_cargo} build --verbose --release

%install
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"

%{local_cargo} install --root %{buildroot}%{_prefix}
rm %{buildroot}%{_prefix}/.crates.toml

mkdir -p %{buildroot}%{_mandir}/man1
install -p -m644 src/etc/man/cargo*.1 \
  -t %{buildroot}%{_mandir}/man1

install -p -m644 src/etc/cargo.bashcomp.sh \
  -D %{buildroot}%{_sysconfdir}/bash_completion.d/cargo

install -p -m644 src/etc/_cargo \
  -D %{buildroot}%{_datadir}/zsh/site-functions/_cargo

# Create the path for crate-devel packages
mkdir -p %{buildroot}%{_datadir}/cargo/registry

%check
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"

# some tests are known to fail exact output due to libgit2 differences
CFG_DISABLE_CROSS_TESTS=1 %{local_cargo} test --no-fail-fast || :

%files
%doc README.md
%{_bindir}/cargo
%{_mandir}/man1/cargo*.1*
%{_sysconfdir}/bash_completion.d/cargo
%{_datadir}/zsh/site-functions/_cargo
%dir %{_datadir}/cargo
%dir %{_datadir}/cargo/registry
