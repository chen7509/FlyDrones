# PX4 XRCE Agent Linux package inventory

The running Ubuntu 24.04.4 WSL2 environment has CMake 3.28.3, Ninja 1.11.1 and GCC 13.3.0. Debian package output shows Boost development 1.83.0, OpenSSL development 3.0.13 and TinyXML2 development 10.0.0. It reports no `libasio-dev`, `libfastcdr-dev`, `libfastrtps-dev`, `libfoonathan-memory-dev` or `libspdlog-dev`. `command -v` found no `MicroXRCEAgent`, `micro_ros_agent` or `colcon`; the bounded CMake-config search found only the system TinyXML2 config among the named packages. The linker cache likewise showed TinyXML2/OpenSSL but no Fast-CDR/Fast-DDS. The package query's exit 1 is expected for missing names; it is not a successful all-package installation check. Exact output, commands, exit statuses and WSL localhost-warning bytes are in `results/agent-linux-inventory-dev-1701/inventory.json` and its sealed evidence copy.

The fixed Agent v2.4.3 superbuild sources and [Fast-DDS 2.14 selection logic](https://fast-dds.docs.eprosima.com/en/2.14.x/installation/configuration/cmake_options.html) were previously audited. `THIRDPARTY=ON` does not force its four child gitlinks: Fast-DDS probes installed packages first unless the per-package option is `FORCE`, and `THIRDPARTY_UPDATE` defaults ON. Thus the system TinyXML2 10 is a plausible selection, while the pinned 2017 TinyXML2 source is only another candidate. Absent Asio may select the internal Asio source. Agent's directly pinned Fast-CDR commit `757d5e4` and Fast-DDS gitlink `1bc9c91` differ. These are source-based predictions, **not a CMake selection result**. No CMake cache, selected ABI, Agent binary, Agent/PX4 transport or DDS provenance was produced. The installed Docker image was not started or inventoried; its contents cannot be inferred from WSL.

At inventory capture completion Windows reported about 0.80 GiB free physical memory, and at the later host preflight about 0.52 GiB, despite WSL reporting 6.7 GiB available within its virtual allocation. Docker had no running container and the selected process scan found no competing PX4/Gazebo/Agent build. A one-job superbuild or a physics trial was not started under this host-memory condition. Source and package inventory cannot be used to claim policy quality, VIO→EKF2 fusion, or five-vehicle capacity; the historical 0.873 RTF five-camera result remains below 0.95.

| Item | Status |
| --- | --- |
| Ubuntu WSL OS/toolchain/package candidates | Read-only observed and raw output retained. |
| Docker image package inventory | Untested. |
| Fixed selected dependency versions, CMake cache, compiler flags and linked runtime closure | Untested. |
| Bounded Agent executable, typed DDS/PX4 handshake, EKF2 and flight | Untested. |

Next, choose and freeze one build environment and exact `THIRDPARTY_*` policy, then capture CMake's actual package selection. Only with sufficient host memory and no competing work should the pinned Agent be built with one job and a bounded timeout. This inventory does not authorize ODOMETRY publication, EKF2 parameter changes or arming.

The read-only capture, independent seven-probe read-back, fixed CMake-source extracts, design, plan and this report are sealed in `evidence/agent-linux-inventory-dev-1701.zip` with a per-member SHA-256/CRC manifest. The capture script first failed under Windows PowerShell 5 when WSL's localhost warning was promoted to a terminating stderr error; the successful capture used PowerShell 7. The failed attempt did not produce an inventory and is reflected by the retained script plus this report; no package result was inferred from it.
