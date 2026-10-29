using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace PersonalWorkstation;

internal static class Program
{
    private static Mutex? _trayMutex;

    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var root = WorkspaceLocator.Find(AppContext.BaseDirectory);
        if (root is null)
        {
            using var picker = new FolderBrowserDialog
            {
                Description = "选择包含 ws.ps1、Config 和 Projects 的工作站文件夹",
                UseDescriptionForTitle = true,
                ShowNewFolderButton = false
            };
            if (picker.ShowDialog() != DialogResult.OK || !WorkspaceLocator.IsRoot(picker.SelectedPath))
            {
                MessageBox.Show("没有找到有效的工作站目录。", "Personal AI Workstation", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            root = picker.SelectedPath;
        }

        if (args.Any(x => string.Equals(x, "--tray", StringComparison.OrdinalIgnoreCase)))
        {
            _trayMutex = new Mutex(true, "Local\\PersonalAIWorkstation.Tray", out var isFirstInstance);
            if (!isFirstInstance)
            {
                OpenWorkbenchPage();
                _trayMutex.Dispose();
                _trayMutex = null;
                return;
            }

            try { Application.Run(new WorkstationTrayContext(root)); }
            finally
            {
                _trayMutex.ReleaseMutex();
                _trayMutex.Dispose();
                _trayMutex = null;
            }
            return;
        }

        Application.Run(new WorkstationForm(root));
    }

    internal static void OpenWorkbenchPage() =>
        Process.Start(new ProcessStartInfo("http://127.0.0.1:8765/workbench") { UseShellExecute = true });
}

internal static class WorkspaceLocator
{
    public static string? Find(string start)
    {
        var current = new DirectoryInfo(start);
        while (current is not null)
        {
            if (IsRoot(current.FullName)) return current.FullName;
            current = current.Parent;
        }
        return null;
    }

    public static bool IsRoot(string path) =>
        File.Exists(Path.Combine(path, "ws.ps1")) &&
        Directory.Exists(Path.Combine(path, "Config")) &&
        Directory.Exists(Path.Combine(path, "Projects"));
}

internal sealed class WorkstationApi : IDisposable
{
    private readonly string _root;
    private readonly HttpClient _http = new() { BaseAddress = new Uri("http://127.0.0.1:8765"), Timeout = TimeSpan.FromMinutes(15) };
    private string _token = "";

    public WorkstationApi(string root) => _root = root;

    public async Task ConnectAsync()
    {
        if (!await TryReadStatusAsync())
        {
            await StartControlCenterAsync();
            var deadline = DateTime.UtcNow.AddSeconds(15);
            while (DateTime.UtcNow < deadline && !await TryReadStatusAsync())
                await Task.Delay(350);
        }

        var page = await _http.GetStringAsync("/workbench");
        var match = Regex.Match(page, "const CONTROL_TOKEN=\\\"(?<token>[0-9a-f]{32})\\\";");
        if (!match.Success) throw new InvalidOperationException("本地控制台没有返回有效的工作站会话令牌。请更新后重新启动工作台。");
        _token = match.Groups["token"].Value;
    }

    private async Task<bool> TryReadStatusAsync()
    {
        try
        {
            using var response = await _http.GetAsync("/api/status");
            return response.IsSuccessStatusCode;
        }
        catch (HttpRequestException) { return false; }
        catch (TaskCanceledException) { return false; }
    }

    private async Task StartControlCenterAsync()
    {
        var script = Path.Combine(_root, "ws.ps1");
        var powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell)) powershell = "pwsh.exe";
        var start = new ProcessStartInfo(powershell)
        {
            WorkingDirectory = _root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-ExecutionPolicy");
        start.ArgumentList.Add("Bypass");
        start.ArgumentList.Add("-File");
        start.ArgumentList.Add(script);
        start.ArgumentList.Add("control-start");

        using var process = Process.Start(start) ?? throw new InvalidOperationException("无法启动 PowerShell。");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(25));
        if (process.ExitCode != 0)
            throw new InvalidOperationException((await stderr).Trim() is { Length: > 0 } error ? error : (await stdout).Trim());
    }

    public async Task<JsonNode?> GetAsync(string path)
    {
        using var response = await _http.GetAsync(path);
        var body = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode) throw ApiError(response.StatusCode, body);
        return JsonNode.Parse(body);
    }

    public async Task<JsonNode?> PostAsync(string path, object payload)
    {
        if (string.IsNullOrWhiteSpace(_token)) throw new InvalidOperationException("工作站尚未连接。");
        using var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Add("X-Workstation-Token", _token);
        using var response = await _http.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode) throw ApiError(response.StatusCode, body);
        return JsonNode.Parse(body);
    }

    private static Exception ApiError(System.Net.HttpStatusCode status, string body)
    {
        try { return new InvalidOperationException(JsonNode.Parse(body)?["error"]?.ToString() ?? $"API 请求失败（{(int)status}）"); }
        catch (JsonException) { return new InvalidOperationException($"API 请求失败（{(int)status}）: {body}"); }
    }

    public void Dispose() => _http.Dispose();
}

internal sealed class WorkstationTrayContext : ApplicationContext
{
    private const string WorkbenchUrl = "http://127.0.0.1:8765/workbench";
    private readonly string _root;
    private readonly NotifyIcon _icon;
    private readonly ContextMenuStrip _menu;
    private readonly ToolStripMenuItem _statusItem;
    private readonly ToolStripMenuItem _startItem;
    private readonly ToolStripMenuItem _stopItem;
    private readonly System.Windows.Forms.Timer _monitor;
    private readonly HttpClient _http = new() { BaseAddress = new Uri("http://127.0.0.1:8765"), Timeout = TimeSpan.FromSeconds(2) };
    private bool _connected;
    private bool _starting;
    private bool _manualStop;
    private DateTime _nextRetryAt;

    public WorkstationTrayContext(string root)
    {
        _root = root;
        _statusItem = new ToolStripMenuItem("状态：正在检查连接") { Enabled = false };
        _startItem = new ToolStripMenuItem("启动 / 检查后台服务", null, async (_, _) =>
        {
            _manualStop = false;
            if (await StartServiceAsync(showError: true)) Program.OpenWorkbenchPage();
        });
        _stopItem = new ToolStripMenuItem("停止后台服务", null, async (_, _) => await StopServiceAsync());
        _menu = new ContextMenuStrip();
        _menu.Items.Add("打开工作台", null, async (_, _) =>
        {
            _manualStop = false;
            if (await StartServiceAsync(showError: true)) Program.OpenWorkbenchPage();
        });
        _menu.Items.Add(_statusItem);
        _menu.Items.Add(new ToolStripSeparator());
        _menu.Items.Add(_startItem);
        _menu.Items.Add(_stopItem);
        _menu.Items.Add(new ToolStripMenuItem("运行连接自检", null, (_, _) => OpenDiagnostics()));
        _menu.Items.Add(new ToolStripMenuItem("打开工作站文件夹", null, (_, _) => OpenRootFolder()));
        _menu.Items.Add(new ToolStripSeparator());
        _menu.Items.Add(new ToolStripMenuItem("仅退出托盘程序", null, (_, _) => ExitThread()));
        _menu.Items.Add(new ToolStripMenuItem("停止服务并退出", null, async (_, _) =>
        {
            await StopServiceAsync();
            ExitThread();
        }));

        _icon = new NotifyIcon
        {
            Text = "Personal AI Workstation · 正在连接",
            Icon = SystemIcons.Application,
            Visible = true,
            ContextMenuStrip = _menu
        };
        _icon.DoubleClick += async (_, _) =>
        {
            _manualStop = false;
            if (await StartServiceAsync(showError: true)) Program.OpenWorkbenchPage();
        };
        _monitor = new System.Windows.Forms.Timer { Interval = 5000 };
        _monitor.Tick += async (_, _) => await RefreshConnectionAsync();
        _monitor.Start();
        ThreadExit += (_, _) => DisposeResources();
        _ = StartOnLaunchAsync();
    }

    private async Task StartOnLaunchAsync()
    {
        if (await StartServiceAsync(showError: true)) Program.OpenWorkbenchPage();
    }

    private async Task<bool> StartServiceAsync(bool showError)
    {
        if (_starting) return _connected;
        _starting = true;
        _manualStop = false;
        _nextRetryAt = DateTime.UtcNow.AddSeconds(20);
        _startItem.Enabled = false;
        _statusItem.Text = "状态：正在启动本机服务…";
        _icon.Text = "Personal AI Workstation · 正在启动";

        try
        {
            if (!await IsConnectedAsync())
            {
                await RunStationCommandAsync("serve-start");
                var deadline = DateTime.UtcNow.AddSeconds(12);
                while (DateTime.UtcNow < deadline)
                {
                    if (await IsConnectedAsync()) break;
                    await Task.Delay(400);
                }
            }

            var connected = await IsConnectedAsync();
            SetConnected(connected);
            if (!connected) throw new InvalidOperationException("本机服务在 12 秒内没有通过健康检查。请运行“连接自检”查看具体原因。");
            _nextRetryAt = DateTime.UtcNow.AddSeconds(15);
            return true;
        }
        catch (Exception ex)
        {
            SetConnected(false);
            _statusItem.Text = "状态：连接失败 · 可运行连接自检";
            _icon.ShowBalloonTip(5000, "工作站服务未连接", ex.Message, ToolTipIcon.Warning);
            if (showError)
                MessageBox.Show(ex.Message, "工作站连接失败", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }
        finally
        {
            _starting = false;
            _startItem.Enabled = true;
        }
    }

    private async Task RefreshConnectionAsync()
    {
        if (_starting) return;
        var connected = await IsConnectedAsync();
        SetConnected(connected);
        if (!connected && !_manualStop && DateTime.UtcNow >= _nextRetryAt)
        {
            _nextRetryAt = DateTime.UtcNow.AddSeconds(20);
            await StartServiceAsync(showError: false);
        }
    }

    private async Task<bool> IsConnectedAsync()
    {
        try
        {
            using var response = await _http.GetAsync("/api/health");
            if (!response.IsSuccessStatusCode) return false;
            using var payload = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync());
            return payload.RootElement.TryGetProperty("ok", out var ok) && ok.GetBoolean()
                && payload.RootElement.TryGetProperty("service", out var service)
                && service.GetString() == "personal-ai-workstation";
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or InvalidOperationException)
        {
            return false;
        }
    }

    private async Task StopServiceAsync()
    {
        if (_starting) return;
        _starting = true;
        _manualStop = true;
        _stopItem.Enabled = false;
        _statusItem.Text = "状态：正在停止本机服务…";
        try
        {
            await RunStationCommandAsync("serve-stop");
            var deadline = DateTime.UtcNow.AddSeconds(8);
            while (DateTime.UtcNow < deadline && await IsConnectedAsync())
                await Task.Delay(400);
            SetConnected(false);
            _statusItem.Text = await IsConnectedAsync() ? "状态：服务仍在退出" : "状态：服务已停止";
        }
        catch (Exception ex)
        {
            _statusItem.Text = "状态：停止请求失败 · 可运行连接自检";
            _icon.ShowBalloonTip(5000, "无法停止工作站服务", ex.Message, ToolTipIcon.Warning);
        }
        finally
        {
            _starting = false;
            _stopItem.Enabled = true;
        }
    }

    private async Task RunStationCommandAsync(string command)
    {
        var script = Path.Combine(_root, "Tools", "workstation.py");
        if (!File.Exists(script)) throw new FileNotFoundException("没有找到工作站服务脚本。", script);
        Exception? lastError = null;

        foreach (var launcher in new[] { (FileName: "python.exe", UseLauncher: false), (FileName: "py.exe", UseLauncher: true) })
        {
            var start = new ProcessStartInfo(launcher.FileName)
            {
                WorkingDirectory = _root,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            if (launcher.UseLauncher) start.ArgumentList.Add("-3");
            start.ArgumentList.Add(script);
            start.ArgumentList.Add("--root");
            start.ArgumentList.Add(_root);
            start.ArgumentList.Add(command);

            try
            {
                using var process = Process.Start(start) ?? throw new InvalidOperationException("无法启动 Python 工作站服务命令。");
                var stdout = process.StandardOutput.ReadToEndAsync();
                var stderr = process.StandardError.ReadToEndAsync();
                await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
                var error = (await stderr).Trim();
                if (process.ExitCode != 0) throw new InvalidOperationException(error.Length > 0 ? error : (await stdout).Trim());
                return;
            }
            catch (Win32Exception ex)
            {
                lastError = ex;
            }
        }

        throw new InvalidOperationException("找不到 Python 3。请安装 Python，或运行工作站连接自检。", lastError);
    }

    private void SetConnected(bool connected)
    {
        _connected = connected;
        _statusItem.Text = connected ? "状态：服务已连接 · 127.0.0.1:8765" : "状态：本机服务未连接";
        _icon.Text = connected ? "Personal AI Workstation · 已连接" : "Personal AI Workstation · 未连接";
        _icon.Icon = connected ? SystemIcons.Information : SystemIcons.Warning;
        _stopItem.Enabled = connected && !_starting;
    }

    private void OpenDiagnostics()
    {
        var powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell)) powershell = "pwsh.exe";
        var start = new ProcessStartInfo(powershell) { WorkingDirectory = _root, UseShellExecute = true };
        start.ArgumentList.Add("-NoExit");
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-ExecutionPolicy");
        start.ArgumentList.Add("Bypass");
        start.ArgumentList.Add("-File");
        start.ArgumentList.Add(Path.Combine(_root, "ws.ps1"));
        start.ArgumentList.Add("workbench-diagnose");
        Process.Start(start);
    }

    private void OpenRootFolder() =>
        Process.Start(new ProcessStartInfo(_root) { UseShellExecute = true });

    private void DisposeResources()
    {
        _monitor.Stop();
        _monitor.Dispose();
        _icon.Visible = false;
        _icon.Dispose();
        _menu.Dispose();
        _http.Dispose();
    }
}

internal sealed class WorkstationForm : Form
{
    private static readonly Color Ink = Color.FromArgb(27, 42, 35);
    private static readonly Color Muted = Color.FromArgb(110, 124, 115);
    private static readonly Color Green = Color.FromArgb(39, 96, 70);
    private static readonly Color Canvas = Color.FromArgb(243, 246, 242);
    private readonly string _root;
    private readonly WorkstationApi _api;
    private readonly TabControl _tabs = new() { Dock = DockStyle.Fill, Font = new Font("Segoe UI", 10), Appearance = TabAppearance.Normal };
    private readonly ToolStripStatusLabel _statusText = new("正在连接本地工作站…");
    private readonly ComboBox _scanProject = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 270 };
    private readonly TextBox _scanFolder = new() { Width = 480, ReadOnly = true };
    private readonly ComboBox _aiProject = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 270 };
    private readonly TextBox _aiRequest = new() { Multiline = true, ScrollBars = ScrollBars.Vertical, Height = 88, Width = 710 };
    private readonly TextBox _actionId = new() { Width = 290 };
    private readonly TextBox _apiOutput = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, WordWrap = false, Height = 180, Width = 710, Font = new Font("Consolas", 9) };
    private readonly TextBox _scanResult = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Height = 150, Width = 710 };
    private JsonObject? _overview;
    private JsonArray _projects = new();
    private JsonArray _apps = new();
    private JsonNode? _v4Status;

    public WorkstationForm(string root)
    {
        _root = root;
        _api = new WorkstationApi(root);
        Text = "Personal AI Workstation";
        AutoScaleMode = AutoScaleMode.Font;
        var workingArea = Screen.FromPoint(Cursor.Position).WorkingArea;
        var availableWidth = Math.Max(480, workingArea.Width - 24);
        var availableHeight = Math.Max(420, workingArea.Height - 24);
        MinimumSize = new Size(Math.Min(820, availableWidth), Math.Min(600, availableHeight));
        Size = new Size(Math.Min(1280, availableWidth), Math.Min(820, availableHeight));
        StartPosition = FormStartPosition.Manual;
        Location = new Point(
            workingArea.Left + Math.Max(0, (workingArea.Width - Width) / 2),
            workingArea.Top + Math.Max(0, (workingArea.Height - Height) / 2));
        BackColor = Canvas;
        Font = new Font("Segoe UI", 10);

        var header = new Panel { Dock = DockStyle.Top, Height = 82, BackColor = Color.White, Padding = new Padding(24, 13, 24, 9) };
        header.Controls.Add(new Label { Text = "Personal AI Workstation", Font = new Font("Segoe UI Semibold", 17), ForeColor = Ink, AutoSize = true, Location = new Point(22, 10) });
        var rootPath = new Label { Text = root, Font = new Font("Segoe UI", 9), ForeColor = Muted, AutoEllipsis = true, Location = new Point(24, 47), Height = 20 };
        header.Controls.Add(rootPath);
        var openRoot = ActionButton("打开工作区文件夹");
        openRoot.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        openRoot.Click += (_, _) => OpenFolder(_root);
        header.Controls.Add(openRoot);
        void LayoutHeader()
        {
            openRoot.Location = new Point(Math.Max(8, header.ClientSize.Width - openRoot.Width - 10), 20);
            rootPath.Width = Math.Max(80, header.ClientSize.Width - openRoot.Width - 70);
        }
        header.Resize += (_, _) => LayoutHeader();
        LayoutHeader();

        _tabs.Padding = new Point(16, 7);
        _tabs.TabPages.Add(MakeTab("总览"));
        _tabs.TabPages.Add(MakeTab("项目"));
        _tabs.TabPages.Add(MakeTab("软件入口"));
        _tabs.TabPages.Add(MakeTab("文件接入"));
        _tabs.TabPages.Add(MakeTab("Codex / API"));
        _tabs.SelectedIndexChanged += (_, _) => RenderSelectedTab();

        var status = new StatusStrip { Dock = DockStyle.Bottom, BackColor = Color.White, SizingGrip = false };
        _statusText.Spring = true;
        _statusText.TextAlign = ContentAlignment.MiddleLeft;
        status.Items.Add(_statusText);
        var layout = new Panel { Dock = DockStyle.Fill, Padding = new Padding(18, 14, 18, 8) };
        layout.Controls.Add(_tabs);
        Controls.Add(layout);
        Controls.Add(status);
        Controls.Add(header);
        Shown += async (_, _) => await InitializeAsync();
        FormClosed += (_, _) => _api.Dispose();
    }

    private static TabPage MakeTab(string title) => new(title) { BackColor = Canvas, Padding = new Padding(14) };

    private async Task InitializeAsync()
    {
        try
        {
            _statusText.Text = "启动并连接工作站本地服务…";
            await _api.ConnectAsync();
            await RefreshDataAsync();
            _statusText.Text = "已连接到 127.0.0.1:8765 · 文件扫描只生成计划，复制须经审查";
            RenderSelectedTab();
        }
        catch (Exception ex)
        {
            _statusText.Text = "本地服务未连接。请检查 Python、PowerShell 和 Logs/control.log。";
            MessageBox.Show(ex.Message, "连接工作站失败", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private async Task RefreshDataAsync()
    {
        _overview = await _api.GetAsync("/api/status") as JsonObject;
        _projects = _overview?["projects"] as JsonArray ?? new JsonArray();
        _apps = await _api.GetAsync("/api/launcher/apps") as JsonArray ?? new JsonArray();
        _v4Status = await _api.GetAsync("/api/v4/status");
        FillProjectChoices();
    }

    private void FillProjectChoices()
    {
        var selectedScan = _scanProject.SelectedItem?.ToString();
        var selectedAi = _aiProject.SelectedItem?.ToString();
        var names = _projects.Select(p => p?["name"]?.ToString()).Where(n => !string.IsNullOrWhiteSpace(n)).Cast<string>().ToArray();
        _scanProject.Items.Clear();
        _aiProject.Items.Clear();
        _scanProject.Items.AddRange(names);
        _aiProject.Items.AddRange(names);
        if (names.Length > 0)
        {
            _scanProject.SelectedItem = names.Contains(selectedScan) ? selectedScan : names[0];
            _aiProject.SelectedItem = names.Contains(selectedAi) ? selectedAi : names[0];
        }
    }

    private void RenderSelectedTab()
    {
        if (_tabs.SelectedIndex == 0) RenderOverview();
        else if (_tabs.SelectedIndex == 1) RenderProjects();
        else if (_tabs.SelectedIndex == 2) RenderApps();
        else if (_tabs.SelectedIndex == 3) RenderFileIntake();
        else RenderCodexApi();
    }

    private void RenderOverview()
    {
        var tab = _tabs.TabPages[0]; tab.Controls.Clear();
        var stack = PageStack();
        stack.Controls.Add(PageHeading("工作区总览", "项目目录、已登记软件和本地服务集中在这里。"));
        var metrics = new FlowLayoutPanel { Width = 1000, Height = 104, WrapContents = true, BackColor = Canvas, Tag = "metrics" };
        var foundTools = Count(_overview?["tools"], x => x?["found"]?.GetValue<bool>() == true);
        var pending = Count(_v4Status?["actions"], x => x?["status"]?.ToString() == "pending");
        metrics.Controls.Add(MetricCard("项目", _projects.Count.ToString(), "本机已登记"));
        metrics.Controls.Add(MetricCard("可用工具", foundTools.ToString(), "来自 tools.json"));
        metrics.Controls.Add(MetricCard("待处理审批", pending.ToString(), "需人工确认"));
        metrics.Controls.Add(MetricCard("软件入口", Count(_apps, x => x?["available"]?.GetValue<bool>() == true).ToString(), "当前可启动"));
        stack.Controls.Add(metrics);
        stack.Controls.Add(Section("常用操作", ButtonRow(
            ActionButton("项目空间", () => _tabs.SelectedIndex = 1),
            ActionButton("软件入口", () => _tabs.SelectedIndex = 2),
            PrimaryButton("扫描资料文件夹", () => _tabs.SelectedIndex = 3),
            ActionButton("Codex / API", () => _tabs.SelectedIndex = 4),
            ActionButton("打开动态控制台", () => OpenUrl("http://127.0.0.1:8765"))
        )));
        stack.Controls.Add(Section("最近项目", ProjectGrid()));
        tab.Controls.Add(stack);
    }

    private void RenderProjects()
    {
        var tab = _tabs.TabPages[1]; tab.Controls.Clear();
        var stack = PageStack();
        stack.Controls.Add(PageHeading("项目空间", "查看项目状态，打开工作目录或状态记录。"));
        var grid = ProjectGrid();
        stack.Controls.Add(Section("已登记项目", grid));
        stack.Controls.Add(ButtonRow(
            ActionButton("打开选中项目文件夹", () => OpenSelectedProject(grid)),
            ActionButton("打开状态文件", () => OpenSelectedStatus(grid)),
            ActionButton("在 PowerShell 中启动 Codex CLI", () => StartCodexSession(SelectedProject(grid)))
        ));
        var note = Body("新项目可继续通过现有工作站命令创建。此窗口不删除或覆盖项目来源文件。", 9, Muted);
        stack.Controls.Add(note);
        tab.Controls.Add(stack);
    }

    private DataGridView ProjectGrid()
    {
        var grid = new DataGridView
        {
            Width = 990, Height = 255,
            ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false,
            RowHeadersVisible = false, SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            MultiSelect = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            BackgroundColor = Color.White, BorderStyle = BorderStyle.None,
            GridColor = Color.FromArgb(230, 235, 230), EnableHeadersVisualStyles = false
        };
        grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(242, 246, 242);
        grid.ColumnHeadersDefaultCellStyle.ForeColor = Ink;
        grid.Columns.Add("name", "项目");
        grid.Columns.Add("state", "管理状态");
        grid.Columns.Add("path", "工作区路径");
        foreach (var p in _projects)
        {
            var name = p?["name"]?.ToString() ?? "";
            var path = p?["path"]?.ToString() ?? Path.Combine(_root, "Projects", name);
            var row = grid.Rows[grid.Rows.Add(name, p?["status"]?.ToString() ?? "", path)];
            row.Tag = new ProjectRef(name, path);
        }
        return grid;
    }

    private void RenderApps()
    {
        var tab = _tabs.TabPages[2]; tab.Controls.Clear();
        var stack = PageStack();
        stack.Controls.Add(PageHeading("软件入口", "从工具登记表读取本机应用。未发现或命令行工具不会被伪装成桌面软件。"));
        var flow = new FlowLayoutPanel { Width = 1000, Height = 100, WrapContents = true, BackColor = Canvas, Tag = "app-grid" };
        foreach (var app in _apps)
        {
            if (app is not JsonObject item) continue;
            var card = new Panel { Width = 300, Height = 145, BackColor = Color.White, BorderStyle = BorderStyle.FixedSingle, Margin = new Padding(4, 4, 10, 10), Padding = new Padding(13) };
            var label = Body(item["name"]?.ToString() ?? "应用", 12, Ink, true);
            label.Location = new Point(13, 12); card.Controls.Add(label);
            var category = Body(item["category"]?.ToString() ?? "", 9, Muted);
            category.Location = new Point(14, 37); card.Controls.Add(category);
            var description = Body(item["description"]?.ToString() ?? "", 9, Muted);
            description.Location = new Point(14, 61); description.MaximumSize = new Size(265, 36); card.Controls.Add(description);
            var available = item["available"]?.GetValue<bool>() == true;
            var state = Body(available ? "● 本机可用" : "○ 未发现", 9, available ? Green : Muted);
            state.Location = new Point(14, 111); card.Controls.Add(state);
            var appId = item["id"]?.ToString() ?? "";
            var launch = PrimaryButton("打开", async () => await LaunchAppAsync(appId));
            launch.Size = new Size(82, 31); launch.Location = new Point(197, 103); launch.Enabled = available; card.Controls.Add(launch);
            card.Tag = new AppCardLayout(label, description, state, launch);
            flow.Controls.Add(card);
        }
        stack.Controls.Add(flow);
        tab.Controls.Add(stack);
    }

    private void RenderFileIntake()
    {
        var tab = _tabs.TabPages[3]; tab.Controls.Clear();
        var stack = PageStack();
        stack.Controls.Add(PageHeading("文件接入", "选择一个具体来源文件夹，为指定项目生成扫描计划；原件保留，不会自动复制。"));
        var selection = new FlowLayoutPanel { Width = 1000, Height = 42, WrapContents = true, BackColor = Canvas };
        selection.Controls.Add(Body("目标项目", 9, Muted));
        selection.Controls.Add(_scanProject);
        selection.Controls.Add(ActionButton("选择来源文件夹…", ChooseScanFolder));
        stack.Controls.Add(selection);
        stack.Controls.Add(Section("来源文件夹", _scanFolder));
        stack.Controls.Add(Section("扫描计划", ButtonRow(
            PrimaryButton("扫描并生成计划", async () => await ScanFolderAsync()),
            ActionButton("打开审批控制台", () => OpenUrl("http://127.0.0.1:8765"))
        )));
        stack.Controls.Add(Section("扫描结果", _scanResult));
        tab.Controls.Add(stack);
    }

    private void RenderCodexApi()
    {
        var tab = _tabs.TabPages[4]; tab.Controls.Clear();
        var stack = PageStack();
        stack.Controls.Add(PageHeading("Codex CLI 与 API", "Codex 通过工作站 PowerShell 和白名单 API 接入。没有任意 PowerShell 命令输入框。"));
        var cliButtons = ButtonRow(
            PrimaryButton("打开 PowerShell Codex CLI", () => StartCodexSession(_aiProject.SelectedItem?.ToString() ?? "")),
            ActionButton("刷新服务与模型状态", async () => await RefreshApiStatusAsync())
        );
        stack.Controls.Add(Section("交互式 CLI", cliButtons));

        var planButton = PrimaryButton("Codex 只读分析", async () => await CreateAiPlanAsync());
        stack.Controls.Add(Section("只读项目分析（ChatGPT Codex 用量）",
            Compose(
                Body("项目", 9, Muted), _aiProject,
                Body("分析需求", 9, Muted), _aiRequest, planButton
            )));

        var actionRow = ButtonRow(
            ActionButton("创建执行申请", async () => await CreateExecutionRequestAsync()),
            ActionButton("批准申请…", async () => await DecideActionAsync("approved")),
            ActionButton("拒绝申请…", async () => await DecideActionAsync("denied")),
            PrimaryButton("执行已批准申请…", async () => await RunExecutionAsync())
        );
        var actionPanel = Compose(Body("动作 ID", 9, Muted), _actionId, actionRow);
        stack.Controls.Add(Section("项目写入需走申请 → 人工批准 → 执行", actionPanel));
        stack.Controls.Add(Section("本地 API / 模型 / 适配器状态", ButtonRow(
            ActionButton("显示 GET /api/status", async () => await ShowApiAsync("/api/status")),
            ActionButton("显示 GET /api/v4/status", async () => await ShowApiAsync("/api/v4/status")),
            ActionButton("课程状态 API", async () => await ShowApiAsync("/api/education/status"))
        )));
        stack.Controls.Add(Section("API 响应", _apiOutput));
        tab.Controls.Add(stack);
    }

    private async Task CreateAiPlanAsync()
    {
        if (!EnsureConnected()) return;
        var project = _aiProject.SelectedItem?.ToString() ?? "";
        var request = _aiRequest.Text.Trim();
        if (string.IsNullOrWhiteSpace(project) || request.Length < 3) { Warn("选择项目并填写分析需求。"); return; }
        if (MessageBox.Show("将通过 Codex CLI 对所选项目进行只读分析，并消耗 ChatGPT 套餐中的 Codex 用量。不会修改项目文件。继续？", "确认调用 Codex", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync("/api/ai-plan", new { project, text = request });
            _apiOutput.Text = $"只读方案：{result?["id"]}\r\n保存位置：{result?["path"]}\r\n\r\n{result?["response"]}";
            _statusText.Text = $"Codex 只读方案已生成：{result?["id"]}";
        });
    }

    private async Task CreateExecutionRequestAsync()
    {
        if (!EnsureConnected()) return;
        var project = _aiProject.SelectedItem?.ToString() ?? "";
        var request = _aiRequest.Text.Trim();
        if (string.IsNullOrWhiteSpace(project) || request.Length < 3) { Warn("选择项目并填写执行需求。"); return; }
        if (MessageBox.Show("这一步只创建待审批动作，不会修改文件。之后仍需单独批准并执行。创建申请？", "创建 Codex 执行申请", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync("/api/v4/execute-request", new { project, text = request });
            _actionId.Text = result?["id"]?.ToString() ?? "";
            _apiOutput.Text = JsonSerializer.Serialize(result, PrettyJson);
            _statusText.Text = $"已创建待审批动作 {_actionId.Text}";
        });
    }

    private async Task DecideActionAsync(string decision)
    {
        if (!EnsureConnected()) return;
        var id = _actionId.Text.Trim();
        if (string.IsNullOrWhiteSpace(id)) { Warn("请先填写待处理的 ACT- 动作 ID。"); return; }
        var verb = decision == "approved" ? "批准" : "拒绝";
        if (MessageBox.Show($"确定{verb}动作 {id}？该决定会写入本地审批记录。", $"{verb} Codex 申请", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync(decision == "approved" ? "/api/v4/execute-approve" : "/api/v4/execute-deny", new { id });
            _apiOutput.Text = JsonSerializer.Serialize(result, PrettyJson);
            _statusText.Text = $"动作 {id}：{result?["status"]}";
        });
    }

    private async Task RunExecutionAsync()
    {
        if (!EnsureConnected()) return;
        var id = _actionId.Text.Trim();
        if (!id.StartsWith("ACT-", StringComparison.Ordinal)) { Warn("请输入有效的 ACT- 动作 ID。"); return; }
        if (MessageBox.Show($"执行 {id} 将调用 Codex CLI 修改指定项目目录；执行前工作站会自动备份。请确认该动作已审阅并批准。现在执行？", "执行已批准动作", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync("/api/v4/execute-run", new { id });
            _apiOutput.Text = $"{JsonSerializer.Serialize(result, PrettyJson)}\r\n\r\n{result?["response"]}";
            _statusText.Text = $"动作执行完成：{id}";
            await RefreshDataAsync();
        });
    }

    private async Task RefreshApiStatusAsync()
    {
        await RunUiActionAsync(async () =>
        {
            await RefreshDataAsync();
            _apiOutput.Text = JsonSerializer.Serialize(_v4Status, PrettyJson);
            _statusText.Text = "本地状态、模型与适配器信息已刷新。";
        });
    }

    private async Task ShowApiAsync(string path)
    {
        await RunUiActionAsync(async () =>
        {
            var result = await _api.GetAsync(path);
            _apiOutput.Text = JsonSerializer.Serialize(result, PrettyJson);
            _statusText.Text = $"已读取 {path}";
        });
    }

    private async Task ScanFolderAsync()
    {
        if (!EnsureConnected()) return;
        var project = _scanProject.SelectedItem?.ToString() ?? "";
        var source = _scanFolder.Text.Trim();
        if (string.IsNullOrWhiteSpace(project) || !Directory.Exists(source)) { Warn("选择目标项目和一个存在的来源文件夹。"); return; }
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync("/api/scan", new { project, source });
            var entries = result?["entries"] as JsonArray ?? new JsonArray();
            var lines = entries.Take(30).Select(x => $"• {x?["source"]}  →  {x?["category"]}");
            _scanResult.Text = $"计划 ID：{result?["id"]}\r\n扫描文件：{entries.Count}\r\n来源：{result?["source"]}\r\n\r\n{string.Join("\r\n", lines)}" + (entries.Count > 30 ? "\r\n…（界面仅预览前 30 条，完整计划已保存）" : "");
            _statusText.Text = $"扫描计划已生成：{result?["id"]}。原文件未改动；请在审批控制台检查计划。";
        });
    }

    private void ChooseScanFolder()
    {
        using var dialog = new FolderBrowserDialog { Description = "选择一个具体资料文件夹；不要选择磁盘根目录或整个用户目录。", UseDescriptionForTitle = true, ShowNewFolderButton = false };
        if (dialog.ShowDialog(this) == DialogResult.OK) _scanFolder.Text = dialog.SelectedPath;
    }

    private async Task LaunchAppAsync(string id)
    {
        if (!EnsureConnected()) return;
        await RunUiActionAsync(async () =>
        {
            var result = await _api.PostAsync("/api/launcher/launch", new { id });
            _statusText.Text = $"已请求启动 {result?["name"]}。";
        });
    }

    private void StartCodexSession(string project)
    {
        if (string.IsNullOrWhiteSpace(project)) { Warn("选择要打开的项目。"); return; }
        var script = Path.Combine(_root, "Tools", "open-codex-session.ps1");
        if (!File.Exists(script)) { Warn("没有找到 Tools/open-codex-session.ps1。"); return; }
        var powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        if (!File.Exists(powershell)) powershell = "pwsh.exe";
        var start = new ProcessStartInfo(powershell) { WorkingDirectory = _root, UseShellExecute = false };
        start.ArgumentList.Add("-NoProfile"); start.ArgumentList.Add("-NoExit");
        start.ArgumentList.Add("-ExecutionPolicy"); start.ArgumentList.Add("Bypass");
        start.ArgumentList.Add("-File"); start.ArgumentList.Add(script);
        start.ArgumentList.Add("-ProjectName"); start.ArgumentList.Add(project);
        Process.Start(start);
        _statusText.Text = $"已打开 {project} 的 PowerShell Codex CLI 会话。";
    }

    private async Task RunUiActionAsync(Func<Task> action)
    {
        try { Cursor = Cursors.WaitCursor; await action(); }
        catch (Exception ex) { _statusText.Text = "操作未完成。"; MessageBox.Show(ex.Message, "工作站操作失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        finally { Cursor = Cursors.Default; }
    }

    private bool EnsureConnected()
    {
        if (!string.IsNullOrWhiteSpace(_apiOutput.Text) || _overview is not null) return true;
        Warn("本地服务尚未就绪，请稍候或重新打开工作台。"); return false;
    }

    private sealed record ProjectRef(string Name, string Path);

    private void OpenSelectedProject(DataGridView grid)
    {
        var selected = grid.CurrentRow?.Tag as ProjectRef;
        if (selected is null) return;
        OpenFolder(selected.Path);
    }

    private void OpenSelectedStatus(DataGridView grid)
    {
        var selected = grid.CurrentRow?.Tag as ProjectRef;
        if (selected is null) return;
        var path = Path.Combine(selected.Path, "12-status.md");
        if (File.Exists(path)) Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        else Warn("项目没有 12-status.md。");
    }

    private string SelectedProject(DataGridView grid) => (grid.CurrentRow?.Tag as ProjectRef)?.Name ?? "";
    private static void OpenFolder(string path) { if (Directory.Exists(path)) Process.Start(new ProcessStartInfo("explorer.exe", $"\"{path}\"") { UseShellExecute = true }); }
    private static void OpenUrl(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    private static void Warn(string text) => MessageBox.Show(text, "Personal AI Workstation", MessageBoxButtons.OK, MessageBoxIcon.Information);
    private static readonly JsonSerializerOptions PrettyJson = new() { WriteIndented = true };

    private sealed class SectionLayout
    {
        public SectionLayout(Control body) => Body = body;
        public Control Body { get; }
        public bool IsLayingOut { get; set; }
    }

    private sealed record HeadingLayout(Label Title, Label Subtitle);
    private sealed record AppCardLayout(Label Title, Label Description, Label State, Button Launch);

    private FlowLayoutPanel PageStack()
    {
        var stack = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, AutoScroll = true, BackColor = Canvas,
            Padding = new Padding(5)
        };
        stack.SizeChanged += (_, _) => ResizePageContent(stack);
        stack.ControlAdded += (_, _) => ResizePageContent(stack);
        return stack;
    }

    private static void ResizePageContent(FlowLayoutPanel stack)
    {
        if (stack.IsDisposed || stack.ClientSize.Width <= 0) return;
        var width = Math.Max(280, stack.ClientSize.Width - stack.Padding.Horizontal - 4);
        foreach (Control control in stack.Controls)
            ResizePageControl(control, width);
    }

    private static void ResizePageControl(Control control, int width)
    {
        switch (control)
        {
            case GroupBox group when group.Tag is SectionLayout:
                group.Width = width;
                ResizeSection(group);
                break;
            case FlowLayoutPanel flow:
                ResizeFlow(flow, width);
                break;
            case Panel panel when panel.Tag is HeadingLayout heading:
                panel.Width = width;
                heading.Subtitle.MaximumSize = new Size(Math.Max(200, width - 8), 0);
                heading.Subtitle.PerformLayout();
                panel.Height = Math.Max(72, heading.Subtitle.Bottom + 4);
                break;
            case Label label:
                label.MaximumSize = new Size(Math.Max(200, width - label.Margin.Horizontal), 0);
                label.PerformLayout();
                break;
            default:
                control.Width = width;
                break;
        }
    }

    private static void ResizeSection(GroupBox group)
    {
        if (group.Tag is not SectionLayout layout || layout.IsLayingOut) return;
        layout.IsLayingOut = true;
        try
        {
            var width = Math.Max(260, group.ClientSize.Width - group.Padding.Horizontal - 8);
            ResizeBody(layout.Body, width);
            layout.Body.Location = new Point(group.Padding.Left + 4, group.Padding.Top + 18);
            group.Height = layout.Body.Bottom + 10;
        }
        finally { layout.IsLayingOut = false; }
    }

    private static void ResizeBody(Control body, int width)
    {
        switch (body)
        {
            case FlowLayoutPanel flow:
                ResizeFlow(flow, width);
                break;
            case Label label:
                label.MaximumSize = new Size(Math.Max(200, width - label.Margin.Horizontal), 0);
                label.PerformLayout();
                break;
            default:
                body.Width = width;
                break;
        }
    }

    private static void ResizeFlow(FlowLayoutPanel flow, int width)
    {
        flow.Width = width;
        if (flow.Tag?.ToString() == "app-grid")
        {
            ResizeAppCards(flow, width);
        }
        else
        {
            foreach (Control child in flow.Controls)
            {
                var childWidth = Math.Max(160, width - child.Margin.Horizontal - flow.Padding.Horizontal);
                switch (child)
                {
                    case TextBox textBox:
                        textBox.Width = childWidth;
                        break;
                    case Label label:
                        label.MaximumSize = new Size(childWidth, 0);
                        label.PerformLayout();
                        break;
                    case ComboBox combo:
                        combo.Width = Math.Min(combo.Width, childWidth);
                        break;
                    case FlowLayoutPanel nested:
                        ResizeFlow(nested, childWidth);
                        break;
                }
            }
        }

        flow.PerformLayout();
        var preferredHeight = flow.GetPreferredSize(new Size(width, 0)).Height;
        flow.Height = Math.Max(1, preferredHeight);
    }

    private static void ResizeAppCards(FlowLayoutPanel flow, int width)
    {
        var cardWidth = Math.Max(220, Math.Min(300, width - 16));
        foreach (Control control in flow.Controls)
        {
            if (control is not Panel card || card.Tag is not AppCardLayout layout) continue;
            card.Width = cardWidth;
            layout.Title.MaximumSize = new Size(cardWidth - 30, 0);
            layout.Description.MaximumSize = new Size(cardWidth - 30, 36);
            layout.State.MaximumSize = new Size(Math.Max(90, cardWidth - layout.Launch.Width - 38), 0);
            layout.Launch.Location = new Point(cardWidth - layout.Launch.Width - 16, 103);
        }
    }

    private static Panel PageHeading(string title, string subtitle)
    {
        var panel = new Panel { Width = 1000, Height = 72, BackColor = Canvas, Margin = new Padding(0, 0, 0, 12) };
        var heading = new Label { Text = title, AutoSize = true, Font = new Font("Segoe UI Semibold", 19), ForeColor = Ink, Location = new Point(0, 0) };
        var description = new Label { Text = subtitle, AutoSize = true, Font = new Font("Segoe UI", 9), ForeColor = Muted, Location = new Point(2, 42) };
        panel.Controls.Add(heading);
        panel.Controls.Add(description);
        panel.Tag = new HeadingLayout(heading, description);
        return panel;
    }

    private static Control Section(string title, Control body)
    {
        var group = new GroupBox { Text = title, Width = 1000, Height = 100, AutoSize = false, Padding = new Padding(12), ForeColor = Green, Font = new Font("Segoe UI Semibold", 10), Margin = new Padding(0, 4, 0, 12) };
        body.Margin = new Padding(4, 6, 4, 8);
        group.Tag = new SectionLayout(body);
        group.Controls.Add(body);
        group.SizeChanged += (_, _) => ResizeSection(group);
        ResizeSection(group);
        return group;
    }

    private static Panel MetricCard(string label, string value, string detail)
    {
        var p = new Panel { Width = 225, Height = 86, BackColor = Color.White, BorderStyle = BorderStyle.FixedSingle, Margin = new Padding(3, 3, 9, 5) };
        p.Controls.Add(new Label { Text = label, AutoSize = true, ForeColor = Muted, Font = new Font("Segoe UI", 9), Location = new Point(12, 8) });
        p.Controls.Add(new Label { Text = value, AutoSize = true, ForeColor = Green, Font = new Font("Segoe UI Semibold", 20), Location = new Point(12, 27) });
        p.Controls.Add(new Label { Text = detail, AutoSize = true, ForeColor = Muted, Font = new Font("Segoe UI", 8), Location = new Point(70, 41) });
        return p;
    }

    private static Button ActionButton(string text, Action? action = null) => ButtonBase(text, action, false);
    private static Button PrimaryButton(string text, Action? action = null) => ButtonBase(text, action, true);
    private static Button ButtonBase(string text, Action? action, bool primary)
    {
        var button = new Button { Text = text, AutoSize = true, Height = 36, FlatStyle = FlatStyle.Flat, BackColor = primary ? Green : Color.White, ForeColor = primary ? Color.White : Ink, Margin = new Padding(3, 3, 8, 3), Padding = new Padding(10, 4, 10, 4), Cursor = Cursors.Hand };
        button.FlatAppearance.BorderColor = primary ? Green : Color.FromArgb(216, 225, 217);
        if (action is not null) button.Click += (_, _) => action();
        return button;
    }

    private static Label Body(string text, int size, Color color, bool bold = false) => new() { Text = text, AutoSize = true, MaximumSize = new Size(960, 0), Font = new Font(bold ? "Segoe UI Semibold" : "Segoe UI", size), ForeColor = color, Margin = new Padding(4, 6, 4, 6) };
    private static FlowLayoutPanel ButtonRow(params Control[] controls)
    {
        var row = new FlowLayoutPanel { AutoSize = false, WrapContents = true, FlowDirection = FlowDirection.LeftToRight, BackColor = Color.White, Margin = new Padding(0), Padding = new Padding(0) };
        row.Controls.AddRange(controls); return row;
    }
    private static FlowLayoutPanel Compose(params Control[] controls)
    {
        var stack = new FlowLayoutPanel { AutoSize = false, FlowDirection = FlowDirection.TopDown, WrapContents = false, BackColor = Color.White, Margin = new Padding(0), Padding = new Padding(0) };
        stack.Controls.AddRange(controls); return stack;
    }
    private static int Count(JsonNode? node, Func<JsonNode?, bool> predicate) => node is JsonArray array ? array.Count(predicate) : 0;
}
