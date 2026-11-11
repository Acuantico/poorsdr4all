// poorsdrvpn: servidor WireGuard en espacio de usuario para PoorSDR4All.
//
// No necesita driver TUN ni permisos de administrador: usa la pila de red
// "netstack" de wireguard-go. Escucha TCP en la IP del túnel y reenvía cada
// conexión al servidor web local de PoorSDR4All.
//
// Protocolo por stdin/stdout (una línea JSON por mensaje):
//   stdin  1ª línea : configuración inicial (ver Config)
//   stdin  después  : {"cmd":"peers","peers":[...]} | {"cmd":"status"}
//   stdout          : {"event":"ready"} | {"event":"status","peers":[...]}
// Si stdin se cierra (PoorSDR4All termina) el proceso sale solo.
package main

import (
	"bufio"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

type Peer struct {
	PublicKey string `json:"public_key"`
	AllowedIP string `json:"allowed_ip"`
}

type Forward struct {
	ListenPort int    `json:"listen_port"`
	Target     string `json:"target"`
}

type Config struct {
	PrivateKey string    `json:"private_key"`
	ListenPort int       `json:"listen_port"`
	Address    string    `json:"address"`
	MTU        int       `json:"mtu"`
	Forwards   []Forward `json:"forwards"`
	// UDPForwards: puertos UDP del túnel que se reenvían a PoorSDR4All (audio WebRTC).
	UDPForwards []Forward `json:"udp_forwards"`
	Peers      []Peer    `json:"peers"`
}

type Command struct {
	Cmd   string `json:"cmd"`
	Peers []Peer `json:"peers"`
}

var outMu sync.Mutex

func emit(v any) {
	outMu.Lock()
	defer outMu.Unlock()
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}

func fail(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "poorsdrvpn: "+format+"\n", a...)
	os.Exit(1)
}

func b64ToHex(s string) (string, error) {
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	if err != nil || len(raw) != 32 {
		return "", fmt.Errorf("clave WireGuard no válida")
	}
	return hex.EncodeToString(raw), nil
}

func peersIpc(peers []Peer) (string, error) {
	var sb strings.Builder
	sb.WriteString("replace_peers=true\n")
	for _, p := range peers {
		pub, err := b64ToHex(p.PublicKey)
		if err != nil {
			return "", err
		}
		fmt.Fprintf(&sb, "public_key=%s\nallowed_ip=%s\n", pub, p.AllowedIP)
	}
	return sb.String(), nil
}

func pipe(a, b net.Conn) {
	var wg sync.WaitGroup
	wg.Add(2)
	cp := func(dst, src net.Conn) {
		defer wg.Done()
		io.Copy(dst, src)
		if tc, ok := dst.(*net.TCPConn); ok {
			tc.CloseWrite()
		}
	}
	go cp(a, b)
	go cp(b, a)
	wg.Wait()
	a.Close()
	b.Close()
}

// reenviarUDP pasa los datagramas de un puerto del túnel a un destino local y
// devuelve las respuestas a cada cliente. Una sesión (socket local) por cliente.
func reenviarUDP(tun net.PacketConn, target string) {
	destino, err := net.ResolveUDPAddr("udp", target)
	if err != nil {
		fmt.Fprintf(os.Stderr, "poorsdrvpn: destino UDP inválido %s: %v\n", target, err)
		return
	}
	type sesion struct {
		local  *net.UDPConn
		ultimo time.Time
	}
	var mu sync.Mutex
	sesiones := map[string]*sesion{}
	go func() { // cierra sesiones inactivas
		for {
			time.Sleep(15 * time.Second)
			mu.Lock()
			for k, s := range sesiones {
				if time.Since(s.ultimo) > 60*time.Second {
					s.local.Close()
					delete(sesiones, k)
				}
			}
			mu.Unlock()
		}
	}()
	buf := make([]byte, 65535)
	for {
		n, origen, err := tun.ReadFrom(buf)
		if err != nil {
			return
		}
		clave := origen.String()
		mu.Lock()
		s := sesiones[clave]
		if s == nil {
			local, err := net.DialUDP("udp", nil, destino)
			if err != nil {
				mu.Unlock()
				continue
			}
			s = &sesion{local: local}
			sesiones[clave] = s
			go func(local *net.UDPConn, origen net.Addr) {
				rbuf := make([]byte, 65535)
				for {
					m, err := local.Read(rbuf)
					if err != nil {
						return
					}
					tun.WriteTo(rbuf[:m], origen)
				}
			}(local, origen)
		}
		s.ultimo = time.Now()
		local := s.local
		mu.Unlock()
		local.Write(buf[:n])
	}
}

func status(dev *device.Device) []map[string]any {
	dump, err := dev.IpcGet()
	if err != nil {
		return nil
	}
	var peers []map[string]any
	var cur map[string]any
	for _, line := range strings.Split(dump, "\n") {
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		switch k {
		case "public_key":
			raw, _ := hex.DecodeString(v)
			cur = map[string]any{"public_key": base64.StdEncoding.EncodeToString(raw)}
			peers = append(peers, cur)
		case "last_handshake_time_sec", "rx_bytes", "tx_bytes":
			if cur != nil {
				n, _ := strconv.ParseInt(v, 10, 64)
				cur[k] = n
			}
		}
	}
	return peers
}

func main() {
	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadBytes('\n')
	if err != nil && len(line) == 0 {
		fail("no se recibió configuración")
	}
	var cfg Config
	if err := json.Unmarshal(line, &cfg); err != nil {
		fail("configuración inválida: %v", err)
	}
	addr, err := netip.ParseAddr(cfg.Address)
	if err != nil {
		fail("dirección inválida: %v", err)
	}
	if cfg.MTU == 0 {
		cfg.MTU = 1380
	}
	priv, err := b64ToHex(cfg.PrivateKey)
	if err != nil {
		fail("%v", err)
	}

	tdev, tnet, err := netstack.CreateNetTUN([]netip.Addr{addr}, nil, cfg.MTU)
	if err != nil {
		fail("no se pudo crear la red virtual: %v", err)
	}
	logger := &device.Logger{
		Verbosef: device.DiscardLogf,
		Errorf: func(f string, a ...any) {
			fmt.Fprintf(os.Stderr, "poorsdrvpn: "+f+"\n", a...)
		},
	}
	dev := device.NewDevice(tdev, conn.NewDefaultBind(), logger)
	peersCfg, err := peersIpc(cfg.Peers)
	if err != nil {
		fail("%v", err)
	}
	ipc := fmt.Sprintf("private_key=%s\nlisten_port=%d\n%s", priv, cfg.ListenPort, peersCfg)
	if err := dev.IpcSet(ipc); err != nil {
		fail("configuración WireGuard rechazada: %v", err)
	}
	if err := dev.Up(); err != nil {
		fail("no se pudo activar el túnel: %v", err)
	}

	for _, f := range cfg.Forwards {
		ln, err := tnet.ListenTCP(&net.TCPAddr{Port: f.ListenPort})
		if err != nil {
			fail("no se pudo escuchar en el túnel (puerto %d): %v", f.ListenPort, err)
		}
		go func(ln net.Listener, target string) {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go func() {
					t, err := net.Dial("tcp", target)
					if err != nil {
						c.Close()
						return
					}
					pipe(c, t)
				}()
			}
		}(ln, f.Target)
	}
	for _, f := range cfg.UDPForwards {
		pc, err := tnet.ListenUDP(&net.UDPAddr{Port: f.ListenPort})
		if err != nil {
			fail("no se pudo escuchar UDP en el túnel (puerto %d): %v", f.ListenPort, err)
		}
		go reenviarUDP(pc, f.Target)
	}
	emit(map[string]any{"event": "ready"})

	for {
		line, err := reader.ReadBytes('\n')
		if len(line) > 0 {
			var cmd Command
			if json.Unmarshal(line, &cmd) == nil {
				switch cmd.Cmd {
				case "peers":
					if s, perr := peersIpc(cmd.Peers); perr == nil {
						dev.IpcSet(s)
					}
				case "status":
					emit(map[string]any{"event": "status", "peers": status(dev)})
				}
			}
		}
		if err != nil {
			break
		}
	}
	dev.Close()
}
