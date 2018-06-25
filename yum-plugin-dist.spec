Name:       yum-plugin-dist
Version:    0.1.0
Release:    1%{?dist}
Summary:    Push rpm files to the repo server via sftp

Group:      System Environment/Base
License:    GPL
URL:        https://github.com/guoxiaod/%{name}
BuildArch:  noarch
Source0:    https://github.com/guoxiaod/%{name}-%{version}.tar.gz
BuildRoot:  %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

Requires:   yum, openssh-clients, python-paramiko

%description
Push rpm files to the repo server via sftp

%prep
%setup -q

%build

%install
rm -rf %{buildroot}
%{__mkdir} -p %{buildroot}%{_sysconfdir}/yum/pluginconf.d/ \
                %{buildroot}%{_prefix}/lib/yum-plugins/

%{__install} -m 0644 dist.conf %{buildroot}%{_sysconfdir}/yum/pluginconf.d/
%{__install} -m 0644 dist.id_rsa %{buildroot}%{_sysconfdir}/yum/pluginconf.d/
%{__install} -m 0644 dist.py %{buildroot}%{_prefix}/lib/yum-plugins/

%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc README.md LICENSE ChangeLog
%{_sysconfdir}/yum/pluginconf.d/dist.conf
%{_sysconfdir}/yum/pluginconf.d/dist.id_rsa
%{_prefix}/lib/yum-plugins/


%changelog
* Mon Jun 25 2018 - Anders Guo<gxd305@gmail.com> 0.1.0
- The first version
