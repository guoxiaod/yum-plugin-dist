NAME=$(shell /bin/awk '/^[Nn]ame/{print $$2; exit;}' *.spec)
VERSION=$(shell /bin/awk '/^[Vv]ersion/{print $$2; exit;}' *.spec)

FILES=ChangeLog  LICENSE  README.md  dist.conf  dist.py dist.id_rsa
RPMBUILD_ROOT=${HOME}/rpmbuild/
ARCH=noarch


build: env
	/bin/mkdir -p ${NAME}-${VERSION}
	/bin/cp ${FILES} ${NAME}-${VERSION}
	/bin/tar -czf ${NAME}-${VERSION}.tar.gz ${NAME}-${VERSION}
	/bin/cp -r ${NAME}-${VERSION}.tar.gz ${RPMBUILD_ROOT}/SOURCES/
	/usr/bin/rpmbuild -D "_topdir ${RPMBUILD_ROOT}" -bb ${NAME}.spec
	/bin/cp -r ${RPMBUILD_ROOT}/RPMS/noarch/${NAME}-${VERSION}*.rpm .
	/bin/rm -rf ${NAME}-${VERSION}
	/bin/rm -rf ${NAME}-${VERSION}.tar.gz

env:
	for i in BUILD  BUILDROOT  RPMS  SOURCES  SPECS  SRPMS; do \
		mkdir -p ${HOME}/rpmbuild/$$i; \
	done

install:
	sudo rpm -ivh --force ${NAME}-${VERSION}*.rpm

test:
	./test.py

t: 
	sudo cp dist.py /usr/lib/yum-plugins/dist.py
	sudo cp dist.conf /etc/yum/pluginconf.d/
	sudo cp dist.id_rsa /etc/yum/pluginconf.d/

clean:
	rm -rf *.tar.gz
	rm -rf *.rpm

push:
	rpm --addsign *.rpm
	yum dist-push *.rpm

setup:
	sudo yum install yum openssh-clients python-paramiko

