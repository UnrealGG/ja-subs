using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace JaSubsApp
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            string dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string py = Path.Combine(dir, @".venv\Scripts\python.exe");
            string script = Path.Combine(dir, "live_ja.py");

            if (args.Length > 0 && args[0] == "--check")
            {
                Console.WriteLine("py=" + py + " exists=" + File.Exists(py));
                Console.WriteLine("script=" + script + " exists=" + File.Exists(script));
                Console.WriteLine("icon=" + Path.Combine(dir, "ja.ico"));
                return;
            }

            if (args.Length > 1 && args[0] == "--shot")
            {
                // 自检用：把窗子画到位图上（不依赖屏幕截图，也不受 DPI 虚拟化影响）
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                MainForm f = new MainForm(dir, py, script);
                f.StartPosition = FormStartPosition.Manual;
                f.Location = new Point(-3000, -3000);
                f.Show();
                Application.DoEvents();
                System.Threading.Thread.Sleep(300);
                Application.DoEvents();
                using (Bitmap bmp = new Bitmap(f.Width, f.Height))
                {
                    f.DrawToBitmap(bmp, new Rectangle(0, 0, f.Width, f.Height));
                    bmp.Save(args[1], System.Drawing.Imaging.ImageFormat.Png);
                }
                f.Close();
                Console.WriteLine("shot saved");
                Console.WriteLine("dpi=" + f.DeviceDpi + " win=" + f.Width + "x" + f.Height + " client=" + f.ClientSize.Width + "x" + f.ClientSize.Height);
                return;
            }

            bool created;
            using (Mutex mtx = new Mutex(true, "JaSubs_SingleInstance", out created))
            {
                if (!created)
                {
                    MessageBox.Show("字幕已经在跑了，看任务栏右下角的图标。", "JaSubs");
                    return;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new MainForm(dir, py, script));
            }
        }
    }

    public class MainForm : Form
    {
        readonly string _dir, _py, _script;
        Process _proc;
        StreamWriter _log;
        NotifyIcon _tray;

        NumericUpDown _size;
        ComboBox _color, _outline, _pos, _mode, _model;
        TrackBar _alpha;
        Label _alphaVal, _status;
        CheckBox _fade, _scale;
        TextBox _device;
        Button _start, _stop, _openLog;

        static readonly string[] COLOR_KEY = { "white", "yellow", "cyan", "green", "pink", "orange" };
        static readonly string[] COLOR_TXT = { "白色", "黄色", "青色", "绿色", "粉色", "橙色" };
        static readonly string[] OUTLINE_KEY = { "none", "thin", "bold" };
        static readonly string[] OUTLINE_TXT = { "无描边", "细描边", "粗描边" };
        static readonly string[] POS_KEY = { "low", "mid", "high" };
        static readonly string[] POS_TXT = { "贴近进度条", "居中偏下", "偏上" };
        static readonly string[] MODE_KEY = { "both", "zh", "ja" };
        static readonly string[] MODE_TXT = { "中日双语", "只看中文", "只看日文" };
        static readonly string[] MODEL_KEY = { "qwen3.5:latest", "qwen2.5:3b" };
        static readonly string[] MODEL_TXT = { "标准 9B（默认，质量最好）", "轻量 3B（省 3.4GB 显存）" };
        static readonly Color WindowBg = Color.FromArgb(24, 26, 30);
        static readonly Color CardBg = Color.FromArgb(38, 41, 47);
        static readonly Color MainText = Color.FromArgb(232, 234, 237);
        static readonly Color MutedText = Color.FromArgb(150, 156, 165);

        string SettingsPath { get { return Path.Combine(_dir, "JaSubs.settings"); } }
        string LogPath { get { return Path.Combine(_dir, "logs", "gui.log"); } }

        public MainForm(string dir, string py, string script)
        {
            _dir = dir; _py = py; _script = script;
            try { Directory.CreateDirectory(Path.Combine(_dir, "logs")); } catch { }
            BuildUi();
            LoadSettings();
            UpdateStatus("就绪（点「开始字幕」）");
        }

        void BuildUi()
        {
            Text = "JaSubs · 日语同传字幕";
            ClientSize = new Size(468, 316);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            BackColor = WindowBg;
            ForeColor = MainText;
            DoubleBuffered = true;
            Font = new Font("Microsoft YaHei UI", 9f);
            AutoScaleMode = AutoScaleMode.None;

            var g1 = new GroupBox();
            g1.Text = "字幕样式";
            g1.ForeColor = MainText;
            g1.BackColor = CardBg;
            g1.SetBounds(12, 8, 444, 160);
            Controls.Add(g1);

            AddLabel(g1, "字号", 14, 20);
            _size = new NumericUpDown();
            _size.Minimum = 12; _size.Maximum = 40; _size.Value = 22;
            _size.SetBounds(56, 18, 56, 24);
            g1.Controls.Add(_size);

            AddLabel(g1, "字色", 128, 20);
            _color = Combo(g1, new Rectangle(172, 18, 84, 24), COLOR_TXT);

            AddLabel(g1, "描边", 268, 20);
            _outline = Combo(g1, new Rectangle(312, 18, 96, 24), OUTLINE_TXT);

            AddLabel(g1, "位置", 14, 51);
            _pos = Combo(g1, new Rectangle(56, 49, 200, 24), POS_TXT);

            AddLabel(g1, "显示", 268, 51);
            _mode = Combo(g1, new Rectangle(312, 49, 96, 24), MODE_TXT);

            AddLabel(g1, "模型", 14, 82);
            _model = Combo(g1, new Rectangle(56, 80, 352, 24), MODEL_TXT);

            AddLabel(g1, "背景", 14, 113);
            _alpha = new TrackBar();
            _alpha.Minimum = 25; _alpha.Maximum = 100; _alpha.Value = 82;
            _alpha.TickStyle = TickStyle.None;
            _alpha.SetBounds(52, 108, 236, 28);
            _alpha.ValueChanged += delegate { _alphaVal.Text = _alpha.Value + "%"; };
            g1.Controls.Add(_alpha);
            _alphaVal = new Label();
            _alphaVal.Text = "82%";
            _alphaVal.SetBounds(292, 113, 44, 20);
            g1.Controls.Add(_alphaVal);

            _fade = new CheckBox();
            _fade.Text = "淡入淡出";
            _fade.Checked = true;
            _fade.SetBounds(338, 108, 100, 22);
            _fade.ForeColor = MainText;
            g1.Controls.Add(_fade);

            _scale = new CheckBox();
            _scale.Text = "高分屏放大";
            _scale.Checked = true;
            _scale.SetBounds(338, 132, 100, 22);
            _scale.ForeColor = MainText;
            g1.Controls.Add(_scale);

            var g2 = new GroupBox();
            g2.Text = "启动";
            g2.ForeColor = MainText;
            g2.BackColor = CardBg;
            g2.SetBounds(12, 174, 444, 92);
            Controls.Add(g2);

            AddLabel(g2, "设备", 14, 24);
            _device = new TextBox();
            _device.SetBounds(56, 21, 150, 24);
            _device.Text = "";
            g2.Controls.Add(_device);
            var tip = new Label();
            tip.Text = "留空 = 跟随默认输出设备";
            tip.ForeColor = MutedText;
            tip.SetBounds(214, 25, 224, 20);
            g2.Controls.Add(tip);

            _start = Btn(g2, "开始字幕", 14, 54);
            _start.Click += delegate { Start(); };
            _stop = Btn(g2, "停止", 104, 54);
            _stop.Enabled = false;
            _stop.Click += delegate { Stop(false); };
            _openLog = Btn(g2, "看日志", 194, 54);
            _openLog.Click += delegate { OpenLog(); };
            var reset = Btn(g2, "恢复默认", 284, 54);
            reset.Click += delegate { ResetDefaults(); };

            _status = new Label();
            _status.Text = "";
            _status.ForeColor = MutedText;
            _status.SetBounds(14, 272, 440, 20);
            Controls.Add(_status);

            var closeTip = new Label();
            closeTip.Text = "字幕条：拖动移动 · 滚轮字号 · Ctrl+滚轮宽度 · 右键 · ✕ 退出";
            closeTip.ForeColor = MutedText;
            closeTip.SetBounds(14, 292, 448, 18);
            Controls.Add(closeTip);

            // 手动按屏幕 DPI 放大整体布局（AutoScaleMode 会自动缩放却不改窗体大小，右侧被切）
            float k = DeviceDpi / 96f;
            if (k > 1.01f)
            {
                Scale(new SizeF(k, k));
            }
            ClientSize = new Size((int)Math.Round(468 * k), (int)Math.Round(316 * k));

            Icon ic = LoadIcon();
            if (ic != null) Icon = ic;
            MakeTray();
        }

        Icon LoadIcon()
        {
            try
            {
                string ico = Path.Combine(_dir, "ja.ico");
                if (File.Exists(ico)) return new Icon(ico);
            }
            catch { }
            try { return Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch { return null; }
        }

        void AddLabel(Control p, string t, int x, int y)
        {
            var l = new Label();
            l.Text = t;
            l.ForeColor = MainText;
            l.SetBounds(x, y, 44, 20);
            p.Controls.Add(l);
        }

        ComboBox Combo(Control p, Rectangle r, string[] items)
        {
            var c = new ComboBox();
            c.DropDownStyle = ComboBoxStyle.DropDownList;
            c.SetBounds(r.X, r.Y, r.Width, r.Height);
            c.Items.AddRange(items);
            c.SelectedIndex = 0;
            p.Controls.Add(c);
            return c;
        }

        Button Btn(Control p, string t, int x, int y)
        {
            var b = new Button();
            b.Text = t;
            b.SetBounds(x, y, 84, 28);
            b.FlatStyle = FlatStyle.System;
            p.Controls.Add(b);
            return b;
        }

        void MakeTray()
        {
            _tray = new NotifyIcon();
            _tray.Icon = Icon ?? SystemIcons.Application;
            _tray.Text = "JaSubs 日语同传字幕";
            _tray.Visible = true;
            var cm = new ContextMenuStrip();
            cm.Items.Add("显示窗口", null, delegate { Show(); WindowState = FormWindowState.Normal; Activate(); });
            cm.Items.Add("开始字幕", null, delegate { Start(); });
            cm.Items.Add("停止", null, delegate { Stop(false); });
            cm.Items.Add(new ToolStripSeparator());
            cm.Items.Add("退出", null, delegate { Close(); });
            _tray.ContextMenuStrip = cm;
            _tray.DoubleClick += delegate { Show(); WindowState = FormWindowState.Normal; Activate(); };
        }

        // ── 启动 / 停止 ──
        void Start()
        {
            if (_proc != null && !_proc.HasExited)
            {
                UpdateStatus("已经在跑了");
                return;
            }
            if (!File.Exists(_py)) { UpdateStatus("找不到 " + _py); return; }
            if (!File.Exists(_script)) { UpdateStatus("找不到 " + _script); return; }

            var sb = new StringBuilder();
            sb.Append("-u \"").Append(_script).Append("\"");
            sb.Append(" --font ").Append((int)_size.Value);
            sb.Append(" --color ").Append(COLOR_KEY[_color.SelectedIndex]);
            sb.Append(" --outline ").Append(OUTLINE_KEY[_outline.SelectedIndex]);
            sb.Append(" --pos ").Append(POS_KEY[_pos.SelectedIndex]);
            sb.Append(" --mode ").Append(MODE_KEY[_mode.SelectedIndex]);
            sb.Append(" --alpha ").Append((_alpha.Value / 100.0).ToString("0.00", CultureInfo.InvariantCulture));
            sb.Append(" --model \"").Append(MODEL_KEY[_model.SelectedIndex]).Append("\"");
            if (!_fade.Checked) sb.Append(" --no-fade");
            if (!_scale.Checked) sb.Append(" --no-scale");
            string dev = _device.Text.Trim().Replace("\"", "");
            if (dev.Length > 0) sb.Append(" --device \"").Append(dev).Append("\"");
            string args = sb.ToString();

            try
            {
                if (_log != null) { _log.Dispose(); _log = null; }
                _log = new StreamWriter(LogPath, false, new UTF8Encoding(true));
                _log.AutoFlush = true;
                _log.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss") + "] python " + args);

                var psi = new ProcessStartInfo(_py, args);
                psi.WorkingDirectory = _dir;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

                _proc = new Process();
                _proc.StartInfo = psi;
                _proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e) { ToLog(e.Data); };
                _proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e) { ToLog(e.Data); };
                _proc.EnableRaisingEvents = true;
                _proc.Exited += delegate
                {
                    try
                    {
                        if (IsHandleCreated) BeginInvoke((Action)delegate { OnExited(); });
                    }
                    catch { }
                };
                _proc.Start();
                _proc.BeginOutputReadLine();
                _proc.BeginErrorReadLine();

                _start.Enabled = false;
                _stop.Enabled = true;
                UpdateStatus("启动中…首次要加载模型，约 10 秒");
            }
            catch (Exception ex)
            {
                UpdateStatus("启动失败：" + ex.Message);
            }
        }

        void ToLog(string line)
        {
            if (line == null || _log == null) return;
            try { _log.WriteLine(line); } catch { }
        }

        void OnExited()
        {
            _start.Enabled = true;
            _stop.Enabled = false;
            UpdateStatus("已停止");
            if (_log != null) { try { _log.Flush(); } catch { } }
        }

        void Stop(bool silent)
        {
            try
            {
                if (_proc != null && !_proc.HasExited) _proc.Kill();
            }
            catch { }
            _start.Enabled = true;
            _stop.Enabled = false;
            if (!silent) UpdateStatus("已停止");
        }

        void OpenLog()
        {
            try
            {
                if (!File.Exists(LogPath)) { UpdateStatus("还没有日志"); return; }
                Process.Start("notepad.exe", LogPath);
            }
            catch (Exception ex) { UpdateStatus("打不开日志：" + ex.Message); }
        }

        void UpdateStatus(string s)
        {
            _status.Text = s;
        }

        // ── 设置持久化 ──
        void ResetDefaults()
        {
            _size.Value = 22;
            _color.SelectedIndex = 0;
            _outline.SelectedIndex = 1;
            _pos.SelectedIndex = 0;
            _mode.SelectedIndex = 0;
            _model.SelectedIndex = 0;
            _alpha.Value = 82;
            _fade.Checked = true;
            _scale.Checked = true;
            _device.Text = "";
            UpdateStatus("已恢复默认");
        }

        void LoadSettings()
        {
            if (!File.Exists(SettingsPath)) return;
            try
            {
                foreach (string raw in File.ReadAllLines(SettingsPath))
                {
                    string line = raw.Trim();
                    int eq = line.IndexOf('=');
                    if (eq <= 0) continue;
                    string k = line.Substring(0, eq).Trim();
                    string v = line.Substring(eq + 1).Trim();
                    switch (k)
                    {
                        case "size": { int n; if (int.TryParse(v, out n)) _size.Value = Math.Max(12, Math.Min(40, n)); break; }
                        case "color": _color.SelectedIndex = IndexOf(COLOR_KEY, v, 0); break;
                        case "outline": _outline.SelectedIndex = IndexOf(OUTLINE_KEY, v, 1); break;
                        case "pos": _pos.SelectedIndex = IndexOf(POS_KEY, v, 0); break;
                        case "mode": _mode.SelectedIndex = IndexOf(MODE_KEY, v, 0); break;
                        case "model": _model.SelectedIndex = IndexOf(MODEL_KEY, v, 0); break;
                        case "alpha": { double d; if (double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) _alpha.Value = Math.Max(25, Math.Min(100, (int)Math.Round(d * 100))); break; }
                        case "fade": _fade.Checked = v == "1"; break;
                        case "scale": _scale.Checked = v == "1"; break;
                        case "device": _device.Text = v; break;
                    }
                }
                UpdateStatus("已载入上次的设置");
            }
            catch { }
        }

        int IndexOf(string[] arr, string v, int fallback)
        {
            for (int i = 0; i < arr.Length; i++) if (arr[i] == v) return i;
            return fallback;
        }

        void SaveSettings()
        {
            try
            {
                var sb = new StringBuilder();
                sb.AppendLine("size=" + (int)_size.Value);
                sb.AppendLine("color=" + COLOR_KEY[_color.SelectedIndex]);
                sb.AppendLine("outline=" + OUTLINE_KEY[_outline.SelectedIndex]);
                sb.AppendLine("pos=" + POS_KEY[_pos.SelectedIndex]);
                sb.AppendLine("mode=" + MODE_KEY[_mode.SelectedIndex]);
                sb.AppendLine("model=" + MODEL_KEY[_model.SelectedIndex]);
                sb.AppendLine("alpha=" + (_alpha.Value / 100.0).ToString("0.00", CultureInfo.InvariantCulture));
                sb.AppendLine("fade=" + (_fade.Checked ? "1" : "0"));
                sb.AppendLine("scale=" + (_scale.Checked ? "1" : "0"));
                sb.AppendLine("device=" + _device.Text.Trim());
                File.WriteAllText(SettingsPath, sb.ToString(), new UTF8Encoding(false));
            }
            catch { }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            SaveSettings();
            Stop(true);
            if (_tray != null) { _tray.Visible = false; _tray.Dispose(); _tray = null; }
            base.OnFormClosing(e);
        }
    }
}
