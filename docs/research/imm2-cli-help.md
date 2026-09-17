# IMM2 8.41 live CLI help appendix

Collected read-only from IBM machine type/model 7914AC1 at 10.0.0.98 on 2026-09-17. This is argument help, not proof that every advertised feature works. No mutating command was executed. See [the reference](imm2-management-reference.md) for tested capabilities and MCP design.

The 69 advertised entries include four CLI utilities (`?`, `help`, `history`, `exit`). The other 65 entries have help below.

Whitespace is normalized for readability; the [JSON evidence](imm2-live-capabilities.json) preserves the captured responses.

## Top-level catalog

```text
help
               ?  --  Display command list
       accseccfg  --  Account security configuration
         adapter  --  Display the information of the PCIe adapters.
        alertcfg  --  Display or change the IMM global remote alert parameters.
    alertentries  --  This command manages the recipients of alerts.
             asu  --  Set UEFI settings
         autoftp  --  View/Edit auto ftp/tftp/sftp setting
       autopromo  --  Automated promotion of IMM backup.
          backup  --  Creates a backup file containing the current system settings.
           batch  --  Executes CLI commands in a file.
        chconfig  --  View/edit Service Advisor Settings
           chlog  --  Display Service Advisor Activity Log entires
        chmanual  --  Manually generate call home request
        clearcfg  --  Resets the IMM to its default settings
        clearlog  --  Clear IMM event log
           clock  --  Display/set date, time, GMT offset, and dst setting
         console  --  Exit CLI, attach to serial console
      cryptomode  --  Set crypto mode settings
        dhcpinfo  --  View DHCP server assigned settings
             dns  --  Displays the current DNS configuration of the IMM.
        ethtousb  --  Display and configure ethernet to ethernet over usb
                      port mapping
          events  --  View and edit event configuration
            exit  --  Exit CLI (log off)
            fans  --  Displays the fan speed for all system fans
            ffdc  --  First Failure Data Capture (service data)
           fuelg  --  Display or set power usage settings
        gprofile  --  Group Profiles
            help  --  Display command list
         history  --  Display history of last 8 commands
        identify  --  Control system locator LED
        ifconfig  --  Ethernet and PPP configuration
            info  --  Display and configure the information associated with the
                      IMM
          keycfg  --  Display, add or delete activation keys
            ldap  --  LDAP configuration
             led  --  Display LED states.
             ntp  --  Displays and configures the Network Time Protocol
     passwordcfg  --  Password configuration
         portcfg  --  Serial port configuration.
     portcontrol  --  Display and control the corresponding port of service
           ports  --  Display and configure port numbers
           power  --  Control server power
         pxeboot  --  Enable or disable pxe next boot status
         readlog  --  Displays the IMM event log, five entries at a time
           reset  --  Reset server
         resetsp  --  Reset IMM
         restore  --  Restores the system settings using the input backup file.
 restoredefaults  --  Reset all IMM settings to factory defaults
           scale  --  Multinode configuration and control.
         sdemail  --  Send service information using e-mail
             set  --  Display or set CLI environment variables
            smtp  --  Display or set smtp server
            snmp  --  Enable or disable the SNMP agent
      snmpalerts  --  This command manages the recipients of snmp alerts
         spreset  --  Reset IMM
           srcfg  --  Serial redirection configuration
          sshcfg  --  Display and configures SSH parameters
             ssl  --  SSL configuration
          sslcfg  --  Displays and configures the status of the SSL Server
                      and SSL Client
         storage  --  Display the information of the storage.
       syshealth  --  System Health
       telnetcfg  --  Display and configures Telnet parameters
           temps  --  Display system temperatures
         thermal  --  Display and configures the thermal mode policy of the host
                      system.
        timeouts  --  Server timeouts configuration
             tls  --  Set minimum TLS Level
          usbeth  --  Enable or disable the inband (Ethernet over USB) interface
           users  --  User profile configuration
           volts  --  Displays all the voltages and voltage thresholds
             vpd  --  Display VPD
system>
```

## accseccfg

```text
accseccfg -h
usage:
   accseccfg [options]
options:
   -legacy  sets account security to a predefined legacy set of defaults
   -high    sets account security to a predefined high set of defaults
   -custom  sets account security to user defined values
   -am      User authentication method (local, ldap, localldap, ldaplocal)
   -lp      Lockout period after maximum login failures (0,1,2,5,10,15,20,30,60,120,180,240 mins)
   -pe      Password expiration time period (between 0 and 365)
   -pr      Password required (on, off), if disabled, complex password rules will be disabled
   -pc      Password complexity rules enabled (on,off)
   -pd      password minimum number of different characters (between 0 and 19)
   -pl      Password length (between 5 and 20)
   -ci      minimum change interval in hours (between 0 and 240)
   -lf      maximum number of login failures (between 0 and 10)
   -chgdft  (on|off) user must change default password after first login
   -chgnew  (on|off) new user must change password after first login
   -rc      Password reuse cycle (between 0 and 5)
   -wt      Web inactivity session timeout (1, 5, 10, 15, 20, none, or user)

system>
```

## adapter

```text
adapter -h
usage:
adapter [options]
options:
    -list - list the PCIe adapters.
    -show target_id - display the detailed information of the target in selected PCIe adapter.
          info         - display hardware information of the target.
          firmware       - display firmware information of the target.
          ports        - display port details of the target(network function only).
          chips        - display chip details of the target(GPU function only).
system>
```

## alertcfg

```text
alertcfg -h
usage:
   alertcfg [-options] - Display or change the IMM global remote alert parameters.
options:
    -rl 0-8        - retry_limit
    -dr 0.0-4.0    - retry_delay
    -da 0.0-4.0    - agent_delay

system>
```

## alertentries

```text
alertentries -h
usage:
   alertentries [options]    - This command manages the recipients of alerts.
options:
   none                      - display all alert entries
   -<number>                 - recipient number<1-12>
   -type <email|syslog>      - alert type email/syslog
   -status <on|off>          - alert_recipient_status on/off
   -log <on|off>             - include event log in email on/off
   -n <name>                 - alert recipient name
   -e <addr>                 - email_address valid email address(aa@bb.com)
   -del                      - delete entry
   -test                     - generate a test alert
   -ip <ipaddr|hostName>     - syslog ip or hostname
   -pn <port number>         - syslog port number
   -crt <all, none, custom:te|vo|po|di|fa|cp|me|in|re|ot>
   -crten [enabled|disabled]
   -wrn <all, none, custom:rp|te|vo|po|fa|cp|me|ot>
   -wrnen [enabled|disabled]
   -sys <all, none, custom:lo|tio|ot|po|bf|til|pf|el|ne>
   -sysen [enabled|disabled]
usage:
   alertentries -crt [parameters]
parameters:
 all
 none
 custom te   Critical Temperature Threshold Exceeded
        vo   Critical Voltage Threshold Exceeded
        po   Critical Power Failure
        di   Hard Disk Drive Failure
        fa   Fan Failure
        cp   CPU Failure
        me   Memory Failure
        in   Hardware Incompatibility
        re   Power redundancy failure
        ot   all other critical events
usage:
   alertentries -wrn [parameters]
parameters:
 all
 none
 custom rp   Power redundancy warning
        te   Warning Temperature Threshold Exceeded
        vo   Warning Voltage Threshold Exceeded
        po   Warning Power Threshold Exceeded
        fa   Non-critical Fan events
        cp   CPU in degraded state
        me   Memory Warning
        ot   All other attention events
usage:
   alertentries -sys [parameters]
parameters:
 all
 none
 custom lo   Successful Remote Login
        tio  Operating System Timeout
        ot   All other informational/system events
        po   System Power On/Off
        bf   Operating System boot failure
        til  Operating System Loader watchdog timeout
        pf   Predicted failure (PFA)
        el   Event log 75% full
        ne   Network change
        au   All Audit Events
system>
```

## asu

```text
asu -h
Display or modify UEFI settings
Usage: [options] command [cmdopts]
  command may be set, show, etc.
  use --help for more information.

system>
```

## autoftp

```text
autoftp -h
Usage:
    autoftp [-options]
    Display/configure the FTP Server of Service Data settings for the IMM.
    The system will not send duplicate events if they are left unacknowledged in
    The system will not send duplicate events if they are left unacknowledged in
    the activity log.
    Options:
        -m: Automated problem reporting mode (ftp, sftp, tftp, disabled)
        Note: for "ftp" all fields below must be set.  For "tftp", only -i and -p are needed.
        -i: FTP server IP address or Hostname for automated problem reporting.
        -p: FTP transmission port for problem reporting (1-65535).
        -u: Quote-delimited FTP User Name for automated problem reporting (63 characters maximum).
        -pw: Quote-delimited FTP password for automated problem reporting (63 characters maximum).
       -epw: Quote-delimited FTP encrypted password for automated problem reporting.
system>
```

## autopromo

```text
autopromo -h
usage:
    autopromo [-options]- Disaplays and configures the automated promotion of IMM backup.
options:
    -en     - Enable/Disable the automated promotion [ enabled, disabled ]

system>
```

## backup

```text
backup -h
usage:
   backup [options]
options: {-f|-pp|-ip|-pn|-u|-pw|-fd}
   -f    filename of backup file
   -pp   password or quote delimited phrase used to encrypt the passwords inside the backup file
   -ip   address of tftp/sftp server
   -pn   port number of tftp/sftp server (default 69/22)
   -u    username for sftp server
   -pw   password for sftp server
   -fd   filename to contain xml description of backup cli commands

system>
```

## batch

```text
batch -h
usage:
   batch [options]
options: {-f|-ip|-pn|-u|-pw}
   -f    filename of batch file
   -ip   address of tftp/sftp server
   -pn   port number of tftp/sftp server (default 69/22)
   -u    username for sftp server
   -pw   password for sftp server
   -verbose

system>
```

## chconfig

```text
chconfig -h
Note: For IMM2, additional options were added for Alternate Contact information
and phone extention and are indicated as such in bold.
Usage:
    chconfig[-options]
    Displays and configures Service Advisor settings:
        -li:    View or accept the Service Advisor Terms and Conditions (view,accept).
        Note:   Terms and Conditions must be accepted before configuring any other parameters.
        -sa:    Support status of Service Advisor (enabled, disabled).
        -sc:    Country code for the Service Support Center (2 character ISO country code).
    Service Advisor Contact Information:
        -co:    Quote-delimited organization/company name of the contact person (30 characters
            maximum).
        -cn:    Quote-delimited name of the contact person (30 characters maximum).
        -cph:   Quote-delimited phone number of the contact person (5-30 characters).
        -cpx:   Quote-delimited phone extension of the contact person (5-30 characters)(tbd characters).
        -ce:    Email address of the contact person in form userid@hostname (30 characters).
    Alternate Service Advisor Contact Information:
        -an:    Quote-delimited name of the alt. contact person (30 characters maximum).
        -aph:   Quote-delimited phone number of the alt. contact person (5-30 characters).
        -apx:   Quote-delimited phone extension of the alt. contact person (5-30 characters)(tbd characters).
        -ae:    Email address ofcd  the alt. contact person in form userid@hostname (30 characters).
    System Location Information:
        -mp:    Quote-delimited phone number for the machine location (5-30 characters).
        Note: IMM2 only.
        -ca:    Quote-delimited address of the machine location (30 characters maximum).
        Note: IMM2 only.
        -cci:   Quote-delimited city of the machine location (30 characters maximum).
        Note: IMM2 only,
        -cs:    State of the machine location (2-3 characters).
        Note: IMM2 only.
        -cz:    Quote-delimited postal code of the machine location (9 alphanumeric characters
            maximum).
        Note IMM2 only.
    HTTP Proxy Settings:
        -loc:   Fully qualified hostname or IP address for HTTP proxy (63 characters maximum).
        -po:    HTTP proxy port (1-65535).
        -ps:    HTTP proxy status (enabled, disabled).
        -pw:    Quote-delimted HTTP proxy password (15 characters maximum).
        -epw:   Quote-delimted HTTP proxy encrypted password (15 characters maximum).
        -u:     Quote-delimited HTTP proxy user name (30 characters maximum).
        Note: All contact information fields as well as the Service Support Center field are
        required before the Support of Service Advisor can be enabled.  If a proxy is
        required, the HTTP Proxy fields must be set too.
system>
```

## chlog

```text
chlog -h
Usage:
   chlog[-options]
       Displays the last five call home events that were generated either by
       the system or the user (most recent call home entry first.
       The system will not send duplicate events if they are not acknowledged as
       corrected in the activity log.)

       -<Event Index>: Specify a call home entry by using the Index from the
       activity Log.
       -ack: Acknowledge/unacknowledged a call home event has been corrected
       (yes,no).
       -s: Only display result of Support Center.
       -f: Only display result of FTP/TFTP Server.
system>
```

## chmanual

```text
chmanual -h
Usage:
    chmanual[-options]
    Generates a manual Call Home or a Test Call Home
        -test: Generate a test Call Home.
    Generates a manual Call Home.
        -desc: Quote-delimited problem description (100 characters maximum).
              (i.e. chmanual -desc "Problem description")
system>
```

## clearcfg

```text
clearcfg -h
usage:
   clearcfg - resets the IMM to its factory default settings

system>
```

## clearlog

```text
clearlog -h
usage:
   clearlog [options] - clear the IMM event log

options:
-t <all|platform|audit>    Event type, choose which type of event to clear.
                           If not specify, all event type will be selected.
   platform       Platform event type.
   audit          Audit event type.
   all            All event type, including platform event and audit event.
system>
```

## clock

```text
clock -h
usage:
   clock [-options]
options:
   -d   - date (mm/dd/yyyy)
   -t   - time (hh:mm:ss)
   -g   - GMT offset
   -dst - daylight savings time (on|off|special case)
For a GMT offset of +2:00, use one of the following values for dst:
   ee   - Eastern Europe
   tky  - Turkey
   bei  - Beirut
   amm  - Amman
   jem  - Jerusalem
   off
For a GMT offset of -7:00, use one of the following values for dst:
   mtn  - Mountain
   maz  - Mazatlan
   off
For a GMT offset of -6:00, use one of the following values for dst:
   mex  - Mexico
   cna  - Central North America
   off
For a GMT offset of -5:00, use one of the following values for dst:
   cub  - Cuba
   ena  - Eastern North America
   off
For a GMT offset of -4:00, use one of the following values for dst:
   asu  - Asuncion
   cui  - Cuiaba
   san  - Santiago
   cat  - Canada_Atlantic
   off
For a GMT offset of -3:00, use one of the following values for dst:
   gtb  - Godthab
   moo  - Montevideo
   bre  - Brazil East
   off

system>
```

## console

```text
console -h
usage:
   console 1       - start a serial redirect console session 1
   console info    - displays detailed information about all sessions
   console kill 1  - terminate an existing session
system>
```

## cryptomode

```text
cryptomode -h

  usage:
   cryptomode [-options] - Displays and configures the compliance mode
                           with the exceptions for encryption
   -set <basic | NIST> - Selects compliance mode
   -esnmpv3 <enabled | disabled> - Allow/disallow SNMPv3 accounts to
           operate in a non-compliant fashion with the NIST compliance mode
   -h - Lists usage and options

system>
```

## dhcpinfo

```text
dhcpinfo -h
usage:
   dhcpinfo eth0 - Display the DHCP settings for eth0
   -server - DHCP server
   -n      - hostname
   -i      - IP address
   -i6     - IPv6 address
   -g      - gateway
   -s      - subnet mask
   -d      - domain name
   -d6     - IPv6 domain name
   -dns1   - primary DNS server
   -dns2   - secondary DNS server
   -dns3   - tertiary DNS server
   -dns61  - IPv6 primary DNS server
   -dns62  - IPv6 secondary DNS server
   -dns63  - IPv6 tertiary DNS server
system>
```

## dns

```text
dns -h
usage:
   dns   [-options] - Displays and configures the current DNS configuration of the IMM.
options:
   -state         <on|off> on/off means DNS source from manual/dhcp
   -i1            IPv4 first ip address
   -i2            IPv4 second ip address
   -i3            IPv4 third ip address
   -i61           IPv6 first ip address
   -i62           IPv6 second ip address
   -i63           IPv6 third ip address
   -ddns          <enabled|disabled> dynamic_DNS_state
   -dnsrc         <dhcp|manual>   domain name source
   -ddn           <ddns domain name> ddns domain name
   -ddncur        current ddns domain name (read only)
   -p <ipv4|ipv6> DNS_server_priority

system>
```

## ethtousb

```text
ethtousb -h
usage:
   ethtousb [-options] - Display and configure ethernet to ethernet over
                         usb port mapping, Allows you to map an external
                         Ethernet port number to a different port number
                         for Ethernet over USB
options:
   -en <enabled|disabled>   - switch this feature.
   -mx port1:port2          - configure the port mapping
                              where x is the map_index, and x=1-10
                              port1 is the External Ethernet port number
                              port2 is the Ethernet over USB port number
   -rm map_index            - remove the port mapping
                              where map_index is 1-10
system>
```

## events

```text
events -h
Usage:
    Events -che[-options]
    View and edit events configuration
        -add : add a call home event into the Call Home Exclusion List
        (Event ID in the format 0xhhhhhhhhhhhhhhhh)
        -rm:    remove a call home event from the Call Home Exclusion List
        (Event ID in the format of 0xhhhhhhhhhhhhhhhh, or all)
    Note: The Service Advisor Terms and Conditions must be accepted first before
    using this command.
system>
```

## fans

```text
fans -h
usage:
   fans - displays the fan speed for all system fans

system>
```

## ffdc

```text
ffdc -h
usage:
   ffdc command [options]

  commands:
      generate - create new service data file
      status   - check status
      copy     - copy existing service data
      delete   - delete existing service data

  options:
   -t [1|4]  type number, where 1=processor dump; 4=service data (default=1)

   additional options for generate and copy commands:
   -f        remote filename or sftp target directory (default is system generated name)
             (for sftp, use full path or trailing / on directory name (~/ or /tmp/)
   -ip       address of tftp/sftp server
   -pn       port number of tftp/sftp server (default 69/22)
   -u        username for sftp server
   -pw       password for sftp server

system>
```

## fuelg

```text
fuelg -h
usage:
fuelg [options]
Displays and configures server power management options
  -pme      <on|off>   Enable or disable power management and capping
  -pcapmode <dc|ac>    Sets power capping mode to ac or dc
  -pcap     value      where value lies between the minimum and maximum power
                       capping values (from fuelg display)

  -pm       <bt|r|rt>  Sets policy mode for loss of redundant power.
            bt           basic with throttling (default)
            rt           redundant with throttling
            r            redundant without throttling
            b            basic without throttling

For systems that support four power supply unit redundancy:
  -hp       <on|off>   Enable or disable maximum power consumption budget.
            on           For all hot-plug components
            off          For current configuration
  -nn       value      Where value specifies the N+N redundancy configuration
                         the valid range and supported configurations are
                         based on the system, current PSU configuration,
                         and settings for -pm and -hp

system>
```

## gprofile

```text
gprofile -h
Usage:
   gprofile [-options] - Displays and configures groups for the IMM2

options:
   -[1-16]          - Group profile slot number
   -clear           - Deletes a group based on the index
   -n <group_name>  - group name (limited to 63 characters, must be unique)
   -a <auth_level>  - Authority Level
                     (super, operator, rbs:<role list>)
       roles:
              nsc   - Network and Security
              am    - User Account Management
              rca   - Remote Console Access
              rcvma - Remote Console and Remote Disk Access
              pr    - Remote Server Power/Restart Access
              bc    - Basic Adapter Configuration
              cel   - Ability to Clear Event Logs
              ac    - Advanced Adapter Configuration
        Note: <role list> is a pipe '|' separated list of roles
   -h               - Help
system>
```

## identify

```text
identify -h
identify [-options]
Illuminates the system locator LED
Option:
     -s: Changes the state of the LED (on/off/blink)
     -d: Turns on the LED for the specified number of seconds.
     -h: Displays the command usage and options.
system>
```

## ifconfig

```text
ifconfig -h
usage:
   ifconfig eth0 [-options]  - ethernet interface configuration
eth0 options:
   -state      - interface status       [enabled, disabled]
   -c          - configuration method   [dhcp, static, dthens]
   -i          - static IP address      <ip_addr>
   -g          - gateway                <ip_addr>
   -s          - subnet mask            <ip_addr>
   -n          - host name              <hostname>
   -auto       - Auto Negotiate         [true, false]
   -vlan       - VLAN                   [enabled, disabled]
   -vlanid     - VLAN ID                <num>
   -r          - data rate              [10, 100]
   -d          - duplex mode            [full, half]
   -m          - MTU                    <num>
   -l          - LAA                    <mac_addr>
   -b          - burn-in MAC Address (read-only)
   -dn         - IPv6 domain name (read-only)
   -ipv6       - IPv6 state             [enabled, disabled]
   -ipv6static - IPV6 static mode       [enabled, disabled]
   -i6         - IPv6 static address    <IPv6 address>
   -p6         - IPv6 static address prefix length <num>
   -g6         - IPv6 static default gateway <IPv6 address>
   -dhcp6      - IPv6 DHCP mode         [enabled, disabled]
   -sa6        - IPv6 Stateless mode    [enabled, disabled]
   -lla        - IPv6 link-local address (read-only)
   -nic        - Switch NIC mode        [shared|dedicated|shared_option_1]
   -failover   - Failover mode          [none|shared|shared_option_1]
   -nssync     - Network setting synchronization        [enabled, disabled]
   -address_table    - ipv6 stateless addresses (read only)
system>
```

## info

```text
info -h
usage:
   info - display and configure the information associated with the Management Module
options:
   -name:      name of the IMM
   -contact:   name of the contact person
   -location:  location of the IMM
   -room:      room id (read only on ITEs)
   -rack:      rack id (read only on ITEs)
   -rup:       rack unit position (read only on ITEs)
   -ruh:       rack unit height (read only)
   -bbay:      blade bay (read only)

system>
```

## keycfg

```text
keycfg -h
usage:
   Display, add or delete activation keys.
Options:
   -add
       -ip tftp ip address
       -pn port number of tftp/sftp server (default 69/22)
       -u  username for sftp server
       -pw password for sftp server
       -f  filename
   -del     n ( where n is a valid ID number from listing)
   -deltype x ( where x is a Type value)
system>
```

## ldap

```text
ldap -h
usage:
   ldap [-options]             - LDAP protocol configuration

options:
   -aom <enabled|disabled>     - Authentication Only Mode for Active
                                 Directory Users
   -a   <loc|ldap|locld|ldloc> - User Authentication Method
   -b   <anon|client|login>    - Anonymous, bind w/ClientDN & password,
                                 with Login Credentials
   -c   <client_dn>            - Client distinguished name
   -d   <search_domain>        - search domain
   -fn  <forest_name>          - forest name
   -f   <group_filter>         - group filter
   -g   <group_search_attr>    - group search attribute
   -l   <string>               - Login Permission Attribute
   -p   <client_pw>            - Client password
   -ep  <client_epw>           - Client encrypted password
                                 (for use with backup/restore)
   -pc  <confirm_pw>           - Confirm password (req'd to change password)
   -r   <root_dn>              - root entry distinguished name (DN)
   -rbs <enabled|disabled>     - Enhanced Role-Based Security for Active
                                 Directory Users
   -s1ip <host name/ip_addr>   - server 1 host name/ip addr
   -s2ip <host name/ip_addr>   - server 2 host name/ip addr
   -s3ip <host name/ip_addr>   - server 3 host name/ip addr
   -s4ip <host name/ip_addr>   - server 4 host name/ip addr
   -s1pn <port_number>         - server 1 port number
   -s2pn <port_number>         - server 2 port number
   -s3pn <port_number>         - server 3 port number
   -s4pn <port_number>         - server 4 port number
   -t   <target_server_name>   - Server Target Name
   -u   <search_attrib>        - UID search attribute
   -v   <off|on>               - get LDAP server address via DNS
   -h                          - lists usage and options

system>
```

## led

```text
led -h
usage:
   led   [-options] - Display LED states.
options:
-l     : get status of all LEDs on system and its subcomponents.
-chklog: turn off "Check Log" LED (off).
-identify   : turn off/on/blink "Enclosure Identify" LED (off/on/blink).
-d sec : turns on the identification LED of the system for the specified number
         of seconds. Notes: The -d option must be used with -identify on.
system>
```

## ntp

```text
ntp -h
ntp [-options]
Displays and configures the Network Time Protocol
options:
 -en <enabled|disabled>    - enable or disable NTP
 -i# <ip_addr or hostname> - NTP server IP address or name
                             # is the index of NTP server (1/2/3/4)
                             ('-i' is the same as 'i1')
 -f  <num>                 - NTP update frequency 3~1440( in minutes)
 -synch                    - Synchronize clock now

system>
```

## passwordcfg

```text
passwordcfg -h
usage:
   passwordcfg [options]
options:
   -legacy  sets account security to a predefined legacy set of defaults
   -high    sets account security to a predefined high set of defaults
   -exp     maximum password age [0 - 365] days
            set to 0 for no expiration
   -cnt     number of previous passwords that cannot be reused [0 - 5]
   -nul     Allow accounts with no password [yes | no]
     -h     Displays the command usage and options.

system>
```

## portcfg

```text
portcfg -h
usage:
   portcfg   [-options] - serial port com configuration
options:
   -b        - baud rate [9600, 19200, 38400, 57600, 115200]
   -climode  - cli mode [0, 1, 2]
         0 - None (CLI disabled)
         1 - CLI with EMS compatible keystroke sequences
         2 - CLI with user defined keystroke sequences
   -p        - parity [none, odd, even]  -
   -s        - stop bits [1, 2]
system>
```

## portcontrol

```text
portcontrol -h
usage:
   portcontrol [-options] - Display and configure port of service
options:
   -ipmi <on|off>       - Enable or disable ipmi-server 623 port
system>
```

## ports

```text
ports -h
usage:
   ports [-options] - Display and configures daemon use port
options:
   -open       - Display open ports
   -reset      - reset to default ports
   -httpp      - HTTP                              <default :80>
   -httpsp     - HTTPS                             <default :443>
   -telnetp    - Telnet Legacy CLI                 <default :23>
   -sshp       - SSH Legacy CLI                    <default :22>
   -snmpap     - SNMP Agent                        <default :161>
   -snmptp     - SNMP Traps                        <default :162>
   -rpp        - Remote Presence                   <default :3900>
   -cimhp      - CIM over HTTP                     <default :5988>
   -cimhsp     - CIM over HTTPS                    <default :5989>
system>
```

## power

```text
power -h
usage:
   power on        [-options]   - power on server
   power off       [-options]   - power off server
   power cycle     [-options]   - power off, then on
   power uefi                   - boot into UEFI's F1 setup
   power state                  - display power state
   power -rp      [alwayson|alwaysoff|restore]   - host power restore policy
options:
   -s                       - shut down OS first
   -every day               - daily or weekly on,off or cycle commands
[Sun|Mon|Tue|Wed|Thu|Fri|Sat|Day|clear]
   -t   time                - time (hh:mm)
additional options for on.
   -d  date                 - date (mm/dd/yyyy)
   -clear                   - clear on date

system>
```

## pxeboot

```text
pxeboot -h
usage:
   pxeboot   [-options] - Display pxeboot states.
options:
    -en <enabled|disabled>    - enable or disable
system>
```

## readlog

```text
readlog -h
usage:
   readlog [-options] - display the IMM event log entries from most recent to oldest, five entries at a time
options:
   -a:    display all log entries
   -f:    reset the counter and display the first five entries
   -date: display entries that meet date criteria
   -sev:  display entries that meet severity criteria
   -i:    IPv4 or IPv6 IP address of the TFTP/SFTP server where the event log is being saved
   -l:    filename is the name of the event log file
   -pn:   port number of TFTP/SFTP server (default 69/22)
   -u:    username for SFTP server
   -pw:   password for SFTP server

system>
```

## reset

```text
reset -h
usage:
   reset    [-options]   - restart the server
options:
   -s         - Shutdown the operating system before the server is reset.
   -d         - Delays performing the reset for the given number of 0-120 seconds.
   -nmi       - The -nmi option will generate an NMI (Non-Maskable Interrupt) on the server.
system>
```

## resetsp

```text
resetsp -h
usage:
   spreset | resetsp - reset the service processor (ASM)

system>
```

## restore

```text
restore -h
usage:
   restore [options]
options: {-f|-pp|-ip|-pn|-u|-pw}
   -f    filename of backup file
   -pp   password or quote delimited phrase used to encrypt the passwords inside the backup file
   -ip   address of tftp/sftp server
   -pn   port number of tftp/sftp server (default 69/22)
   -u    username for sftp server
   -pw   password for sftp server

system>
```

## restoredefaults

```text
restoredefaults -h
usage:
   restoredefaults - resets all IMM settings to factory defaults

system>
```

## scale

```text
scale -h
usage:
scale [-options <arg1,arg2,...,arg>] - Multinode configuration and control.
Note: Entering command with no parms will display all relevant information.

options:
-auto                                    - auto create partition.
-auto <Node Key>                         - auto create partition.
                                           Note: If current system supports
                                           selection of primary node, then the
                                           node with specified Node Key would be
                                           chosen as primary node of the
                                           partition being created.
-create <Node1 Key> <Node2 Key> ....     - create a partition.
                                           Note: If current system supports
                                           selection of primary node, then the
                                           node with first Node Key in the
                                           list would be chosen as primary
                                           node of the partition being
                                           created. The Node Key list is a
                                           space separated list of all the
                                           Node Keys for the nodes in the
                                           partition.
-create_with_physical_node_id  <PhysNodeId1 PhysNodeId2>....
                                         - create a partition.
                                           Note: If current system supports
                                           selection of primary node, then the
                                           node with first Physical Node Id in
                                           list would be chosen as primary
                                           node of the partition being
                                           created. The Physical Node Id list
                                           is a space separated list of all
                                           the Physical Node Ids for the
                                           nodes in the partition.
-delete {-partid <id> | -node <Node Key>}- delete a partition.
-delete                                  - delete all partitions
                                           information in the complex.
-mode <standalone|partition> {-partid <id> | -node <Node Key>}
                                         - set partition mode to standalone.
                                           or partition.
-start {-partid <id> | -node <Node Key>} - power on partition or node.
-reset {-partid <id> | -node <Node Key>} - reset partition or node.
-stop  {-partid <id> | -node <Node Key>} - power off partition or node.
-poweron   {-partid <id> | -node <Node Key>}
                                         - power on partition or node.
-poweroff  {-partid <id> | -node <Node Key>}
                                         - power off partition or node.
-powercycle  {-partid <id> | -node <Node Key>}
                                         - power cycle partition or node.
-partid <id>                             - list partition information.
-node <Node Key>                         - list node information.
-smp                                     - list SMP hardware information.
-h or -help                              - list command usage and options.
system>
```

## sdemail

```text
sdemail -h
Usage:
        sdemail[-options]
        Emails service information to the specified recipients.
            - subj: Quote-delimited email subject (119 characters maximum)
            - to:   Recipient's email address.
        Multiple addresses separated with a comma (119 characters maximum):
        Userid1@hostname1,userid2@hostname2
        The userid can be alphanumeric characters, ".", "-", or "_",
        but must begin and end with alphanumeric characters.
        The hostname can be alphanumeric characters, ".", "-", or "_".
        It must contain two domain Items. Every domain item should begin and
        end with alphanumeric
        characters and the last domain item should be 2 - 20 alphabetic
        characters.
        Note: -to option is required to send an email.
system>
```

## set

```text
set -h
usage:
 set [variable] [=] [value]
 Displays or sets CLI enviroment variables
   set                    display all environment variables
   set variable           display the environment variable
   set var                display variables that begin with 'var'
   set variable=value     set the environment variable
   set variable value     set the environment variable
   set variable=          unset the environment variable
Where 'variable' contains alphanumeric, _, . or the / characters.

Environment variables may be used on the CLI command line or in batch files.
If 'var' is an enviroment variable, then $var will be converted to the value
of the environment variable.  The variable name may also be enclosed in
braces e.g. ${var}.

system>
```

## smtp

```text
smtp -h
usage:
   smtp [-options]
Display or set the smtp server for email alerts send
options:
   -s                       - SMTP server IP address or hostname
   -pn                      - SMTP server port number
   -auth <enabled|disabled> - SMTP authentication support, valid values are
                              enabled and disabled
   -authn                   - SMTP authentication user name
                              (limited to 256 characters)
   -authpw                  - SMTP authentication password
                              (limited to 256 characters)
   -authepw                 - SMTP authentication encrypted password
   -authmd <CRAM-MD5|LOGIN> - SMTP authentication method, valid values are
                              CRAM-MD5 and LOGIN.
system>
```

## snmp

```text
snmp -h
usage:
  snmp  [-options] - Enable/disable the SNMPv1 or SNMPv3 agent
options:
   -a    -  SNMPv1 agent (on|off)
       Note:
         To enable the SNMPv1 agent, the following criteria must be met:
         - IMM contact is specified,
         - IMM location is specified,
         - At least one Community name is specified, and
         - At least one valid IP address is specified for that Community
   -a3   -  SNMPv3 agent (on|off)
       Note:
         To enable the SNMPv3 agent, the following criteria must be met:
         - IMM contact is specified,
         - IMM location is specified
   -t    -  SNMP traps (on|off)
   -l    -  location (limited to 47 characters)
   -cn   -  contact name (limited to 47 characters)
   -cx   -  SNMP community x name
              (limited to 15 characters) (x can be 1, 2 or 3)
   -cxiy -  community x IP address/hostname y
              (limited to 63 characters) (x or y can be 1, 2 or 3)
       Note:
         It can only contain dots, underscores, minus signs, letters and
         digits. No embedded spaces or consecutive periods are allowed.
   -cax  -  community x access type for SNMPv1
              (get, set, trap) (x can be 1, 2 or 3)

system>
```

## snmpalerts

```text
snmpalerts -h
usage:
   snmpalerts [options]
options:
   -status   - on/off
   -crt      - all, none, custom:te|vo|po|di|fa|cp|me|in|re|ot
   -crten    - enabled/disabled
   -wrn      - all, none, custom:rp|te|vo|po|fa|cp|me|ot
   -wrnen    - enabled/disabled
   -sys      - all, none, custom:lo|tio|ot|po|bf|til|pf|el|ne
   -sysen    - enabled/disabled
usage:
   snmpalerts -crt [parameters]
parameters:
 all
 none
 custom te   Critical Temperature Threshold Exceeded
        vo   Critical Voltage Threshold Exceeded
        po   Critical Power Failure
        di   Hard Disk Drive Failure
        fa   Fan Failure
        cp   CPU Failure
        me   Memory Failure
        in   Hardware Incompatibility
        re   Power redundancy failure
        ot   all other critical events
usage:
   snmpalerts -wrn [parameters]
parameters:
 all
 none
 custom rp   Power redundancy warning
        te   Warning Temperature Threshold Exceeded
        vo   Warning Voltage Threshold Exceeded
        po   Warning Power Threshold Exceeded
        fa   Non-critical Fan events
        cp   CPU in degraded state
        me   Memory Warning
        ot   All other attention events
usage:
   snmpalerts -sys [parameters]
parameters:
 all
 none
 custom lo   Successful Remote Login
        tio  Operating System Timeout
        ot   All other informational/system events
        po   System Power On/Off
        bf   Operating System boot failure
        til  Operating System Loader watchdog timeout
        pf   Predicted failure (PFA)
        el   Event log 75% full
        ne   Network change
system>
```

## spreset

```text
spreset -h
usage:
   spreset | resetsp - reset the service processor (ASM)

system>
```

## srcfg

```text
srcfg -h
usage:
   srcfg [options] - configure the serial redirection
options:
   -entercliseq   - enter cli key sequence
system>
```

## sshcfg

```text
sshcfg -h
usage:
   sshcfg [-options] - Displays and configures SSH parameters
options:
   -cstatus     - Status of CLI SSH [ enabled, disabled ]
   -hk          - hk  [ gen, rsa ]
       gen - generates ssh server private key
       rsa - display server rsa public key

system>
```

## ssl

```text
ssl -h
usage:
   ssl [-options]           - SSL configuration
   -ce <on | off>           - enable/disable ssl client
   -se <on | off>           - enable/disable ssl server
   -cime <on | off>         - enable/disable cim over https ssl server
   -h                       - lists usage and options

system>
```

## sslcfg

```text
sslcfg -h
usage:
   sslcfg   [-options] - Displays and configures the status of the SSL Server and SSL Client,
options:
  -server: SSL Server status (enabled, disabled).
           Note: SSL can only be enabled if a certificate is in place
  -client: SSL Client status (enabled, disabled)
           Note: SSL can be enabled if a server or client certificate is in place
  -cim: CIM over HTTPS status (enabled, disabled)
        Note: SSL can be enabled if a server or client certificate is in place
  -cert: Generate a self-signed certificate (server, client, cim, storekey)
  -csr:  Generate a CSR (server, client, cim, storekey)
  -csrform: The format of the CSR will be exported in (der, pem)
  -i:    IP address for TFTP/SFTP server when uploading a certificate,
         or downloading a certificate/CSR
  -pn:  port number of tftp/sftp server (default 69/22)
  -u:   username for sftp server
  -pw:  password for sftp server
  -l:   Filename when downloading or uploading a certificate or CSR. If not
          specified while download, the default name for that file will
          be used and displayed
  -dnld: Downloads the specified file.
         Note: this option takes no arguments, but must be used with
               -cert/-csr (server/client/cim/storekey), as well as -i (and optionally -l)
  -upld: Imports the specified certificate.
         Note: this option takes no arguments, but must be used with -cert
               (server/client/cim/storekey) and -i and -l.
  -tcx:  Trusted certificate x for the ssl client (x = 1, 2, 3 or 4)
         (import, download, remove)
Required options for generating a self-signed certificate or CSR
  -c:      Country (2 letter code)
  -sp:     Quote-delimited State or Province (max 60 chars)
  -cl:     Quote-delimited City or Locality (max 50 chars)
  -on:     Quote-delimited Organization Name (max 60 chars)
  -hn:     IMM hostname (max 60 chars)
Optional options for generating a self-signed certificate or CSR
  -cp:     Quote-delimited Contact Person (max 60 chars)
  -ea:     Email Address (max 60 chars)
  -ou:     Quote-delimited Organizational Unit (max 60 chars)
  -s:      Quote-delimited Surname (max 60 chars)
  -gn:     Quote-delimited Given Name (max 60 chars)
  -in:     Quote-delimited Initials (max 20 chars)
  -dq:     Quote-delimited DN Qualifier (max 60 chars)
Optional options for generating a CSR
  -cpwd:   Challenge Password (min 6 chars, max 30 chars)
  -un:     Quote-delimited Unstructured Name (max 60 chars)
system>
```

## storage

```text
storage -h
usage:
    storage [-options]
options
    -list <controllers|pools|volumes|drives>     - list the storage targets managed by IMM.
        -target target_id       - list the storage targets according to the target_id.
    -list flashdimms             - list the flashdimms managed by IMM.
    -list devices                 - display all storage devices status.
    -show target_id            - display the detail information of the selected target managed by IMM.
        info                        - display information of the target.
        firmware                 - display firmware information of the target (Controller, Drive and flashdimms only).
system>
```

## syshealth

```text
syshealth -h
usage:
   syshealth summary       - display the system health summary
   syshealth activeevents  - display active events

system>
```

## telnetcfg

```text
telnetcfg -h
usage:
   telnetcfg [-options] - Displays and configures telnet parameters
options:
   -en          - en  [ 1, 2, disabled ]
                 (Changes to this option will result in connection lost.)
       1 - enable telnet connection for 1 user
       2 - enable telnet connection for 2 users
       disabled  - disable telnet connection

system>
```

## temps

```text
temps -h
usage:
   temps - displays temperatures and thresholds in degrees Farenheit/Celsius
   column headings:
        WR is warning reset
        W is warning
        T is temperature (current)
        SS is soft shutdown
        HS is hard shutdown

system>
```

## thermal

```text
thermal -h
usage:
   thermal [-options] - Display and configures the thermal mode policy of the host system.
options:
   -mode <normal | performance>
system>
```

## timeouts

```text
timeouts -h
usage:
   timeouts [-options] - server timeouts configuration
options:
   -o <disabled|2.5|3|3.5|4|10>                                       - OS timeout (minutes)
   -l <disabled|0.5|1|1.5|2|2.5|3|3.5|4|4.5|5|7.5|10|15|20|30|60|120> - Loader timeout (minutes)
   -f <disabled|0.5|1|2|3|4|5|7.5|10|15|20|30|60|120>                 - Power off delay (minutes)

system>
```

## tls

```text
tls -h

  usage:
   tls [-options] - configures the minimum TLS level
   -min <1.0 | 1.1 | 1.2> - Selects the minimum TLS level
   -h - Lists usage and options

system>
```

## usbeth

```text
usbeth -h
Note: 1.The OS IP configuration settings is not used to set the OS IP address of Ethernet Over USB interface
but is used to notify IMM that OS IP address of Ethernet over USB has changed.
      2.Before you configure three IP settings for Ethernet over USB, you need to manually configure
the OS IP address of Ethernet over USB interface in your local operating system.
usage:
   usbeth [options]
options:
   -en <enabled|disabled> - Enable or disable the inband (Ethernet over USB) interface.
   -ip <ip_addr>    Ethernet over USB interface IP address for IMM
   -sn <ip_addr>    Ethernet over USB interface subnet mask for IMM
   -ipos <ip_addr>  Ethernet over USB interface IP address for OS

system>
```

## users

```text
users -h
usage:
   users [-options] - display/configure user accounts
options:
   -[1-12]  - user account number
   -l       - display password expiration days
   -n       - username (limited to 16 characters)
   -p       - password (limited to 20 characters)
   -ep      - encrypted password
            - null to create an account without a password
   -a       - authority level (super, ro, custom:am|rca|rcvma|pr|cel|bc|nsc|ac)
      am    - User account management access
      rca   - Remote console access
      rcvma - Remote console and remote disk (virtual media) access
      pr    - Remote server power/restart access
      cel   - Ability to clear event logs
      bc    - Adapter Configuration (basic)
      nsc   - Adapter Configuration (network and security)
      ac    - Adapter Configuration (advanced)
      Note: the above custom permission flags can be used in any combination
   -clear   - clear user account
   -curr    - display current users
   -sauth   (HMAC-MD5|HMAC-SHA|none)  - snmpv3 authentication protocol
   -spriv   (CBC-DES|AES|none)        - snmpv3 privacy protocol
   -spw     password                  - snmpv3 privacy password
   -sepw    encryptedpassword         - snmpv3 privacy password (encrypted)
   -sacc    (Get|Set)                 - snmpv3 Access type
   -strap   hostname                  - snmpv3 trap hostname

   -pk      - SSH public keys options:
       -e       - Displays the entire key in OpenSSH format
       -remove  - Removes the specified key for the specified user
       -add     - Adds a public key for the specified user
       -upld    - Used to upload a public key in OpenSSH/RFC4716 format
       -dnld    - Used to download the specified public key to a TFTP/SFTP server
       -i       - IP address of the TFTP/SFTP
       -pn      - port number of tftp/sftp server (default 69/22)
       -u       - username for sftp server
       -pw      - password for sftp server
       -l       - Filename of the key file when uploading or downloading via TFTP/SFTP
       -af      - accept connections from host, in the format: from="<list>", where
                  <list> is a comma-separated list of hostnames and IP addresses
                  (limited to 511 characters)
       -cm      - comment (limited to 255 characters, must be quote-delimited)

system>
```

## volts

```text
volts -h
usage:
   volts - displays all the voltages and voltage thresholds
   column headings:
        HSL is hard shutdown low
        SSL is soft shutdown low
        WL is warning low
        WRL is warning reset low
        V is voltage
        WRH is warning reset high
        WH is warning high
        SSH is soft shutdown high
        HSH is hard shutdown high

system>
```

## vpd

```text
vpd -h
usage:
   vpd sys  - displays Vital Product Data for the system
   vpd imm  - displays Vital Product Data for the Management Controller(imm)
   vpd uefi - displays Vital Product Data for system BIOS
   vpd dsa  - displays Vital Product Data for system Diag
   vpd fw   - displays Vital Product Data for the system firmware
   vpd comp - displays Vital Product Data for the system components

system>
```

## Embedded ASU subcommands

```text
asu --help
Advanced setting utility (internal): version 1.0
Usage: [options] command [cmdopts]
options:
   -v|--verbose      verbose output
      --help         display main help
cmdopts:
      --help         help for the command
   See individual commands for more command options

commands:
   help <setting>             display help for setting
   set <setting value> [...] set UEFI setting to input value
   show [cmdopts] <setting>   display setting=value
   showvalues <setting>       display possible values for use with 'set'
   showgroups <setting>       display group names
   delete <setting>       delete an instance of a setting
transactions:
  create and execute batch mode commands
   tropen <id>                create new transaction file <id>
   trset  <id> <setting value> ...  transaction set setting
   trlist <id>                display contents of transaction file <id>
   trcommit <id>              commit transaction file <id>
   trrm   <id>                delete transaction file <id>

 where:
 <id> is an identifying string up to 3 characters long
 <setting> may be "all", a group, or a setting name.
 <setting> may more be than one name except on 'set' command.
 <setting> may contain wildcards (*?).
 Examples: show all; show processors memory; show *.DIMM*
ok
system>
```
