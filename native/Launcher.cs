// native messaging 宿主：只做一件事——把本地字幕服务（pythonw，无窗口）拉起来
// 浏览器点“开启字幕”时 Chrome/Edge 会启动本程序，它拉起 server_ws.py 后立刻退出。
using System;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

class Launcher
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO
    {
        public int cb;
        public string lpReserved, lpDesktop, lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct PROCESS_INFORMATION
    {
        public IntPtr hProcess, hThread;
        public int dwProcessId, dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcess(string app, StringBuilder cmd, IntPtr pa, IntPtr ta,
        bool inherit, uint flags, IntPtr env, string cwd, ref STARTUPINFO si, out PROCESS_INFORMATION pi);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr h);

    const uint CREATE_NO_WINDOW = 0x08000000;
    const uint CREATE_BREAKAWAY_FROM_JOB = 0x01000000;
    const int STARTF_USESHOWWINDOW = 0x00000001;

    static bool PortOpen(int port)
    {
        try
        {
            using (var c = new TcpClient())
            {
                var t = c.BeginConnect("127.0.0.1", port, null, null);
                if (!t.AsyncWaitHandle.WaitOne(300)) return false;
                c.EndConnect(t);
                return true;
            }
        }
        catch { return false; }
    }

    static bool Spawn(string exe, string args, string cwd, out string err)
    {
        err = "";
        string cmd = "\"" + exe + "\" " + args;
        for (int attempt = 0; attempt < 2; attempt++)
        {
            // 第一次带 BREAKAWAY：万一被浏览器放进 job 里，子进程也不会被一起收走
            uint flags = CREATE_NO_WINDOW | (attempt == 0 ? CREATE_BREAKAWAY_FROM_JOB : 0);
            var si = new STARTUPINFO();
            si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
            si.dwFlags = STARTF_USESHOWWINDOW;
            si.wShowWindow = 0; // SW_HIDE
            PROCESS_INFORMATION pi;
            if (CreateProcess(null, new StringBuilder(cmd), IntPtr.Zero, IntPtr.Zero, false,
                              flags, IntPtr.Zero, cwd, ref si, out pi))
            {
                CloseHandle(pi.hProcess);
                CloseHandle(pi.hThread);
                return true;
            }
            err = "CreateProcess error " + Marshal.GetLastWin32Error();
        }
        return false;
    }

    static void Send(string json)
    {
        byte[] b = Encoding.UTF8.GetBytes(json);
        Stream o = Console.OpenStandardOutput();
        byte[] len = BitConverter.GetBytes((uint)b.Length);
        o.Write(len, 0, 4);
        o.Write(b, 0, b.Length);
        o.Flush();
    }

    static void Log(string msg)
    {
        try
        {
            string f = Path.Combine(Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location),
                                    "launcher.log");
            File.AppendAllText(f, DateTime.Now.ToString("HH:mm:ss") + "  " + msg + "\r\n", Encoding.UTF8);
        }
        catch { }
    }

    static int Main()
    {
        string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
        bool already = PortOpen(8765);
        bool ok = true;
        string err = "";
        Log("被调用 already=" + already);
        if (!already)
        {
            string py = Path.Combine(root, @".venv\Scripts\pythonw.exe");
            string script = Path.Combine(root, "server_ws.py");
            if (!File.Exists(py)) { ok = false; err = "找不到 pythonw.exe"; }
            else if (!File.Exists(script)) { ok = false; err = "找不到 server_ws.py"; }
            else { ok = Spawn(py, "-u \"" + script + "\" --loopback", root, out err); Log("拉起服务 ok=" + ok + " " + err); }
        }
        Log("返回 ok=" + ok + " err=" + err);
        Send("{\"ok\":" + (ok ? "true" : "false") + ",\"already\":" + (already ? "true" : "false")
             + ",\"error\":\"" + err.Replace("\\", "\\\\").Replace("\"", "'") + "\"}");
        return 0;
    }
}
