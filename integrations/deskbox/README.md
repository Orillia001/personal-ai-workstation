# DeskBox 联动补丁

基于官方 DeskBox v1.5.7：https://github.com/Tianyu199509/DeskBox/tree/v1.5.7 。保留上游 LICENSE，补丁含派生源码，应按该许可证处理。仓库不含上游完整源码和二进制。

在上游 v1.5.7 源码根目录应用 `git apply /path/to/workstation-link.patch`。需要 .NET 10 SDK；先使用 x64/win-x64 还原 DeskBox 与 DeskBox.Updater，再构建：

```powershell
dotnet restore src/DeskBox/DeskBox.csproj -p:Platform=x64 -r win-x64
dotnet restore src/DeskBox.Updater/DeskBox.Updater.csproj -p:Platform=x64 -r win-x64
dotnet build src/DeskBox/DeskBox.csproj -c Debug -p:Platform=x64 -r win-x64 -p:SelfContained=true -p:DeskBoxShellThumbnailProxy=false -p:WindowsAppSDKSelfContained=true --output 'src/DeskBox/bin/Debug/net10.0-windows10.0.22621.0/' --no-restore
```

输出路径保留末尾 `/`，否则可能生成错误的 XAML 资源路径。此版本使用当前用户命名管道，在 DeskBox UI 线程操作原生待办并等待保存；工作站每 5 秒刷新。沿用 DeskBox 原有数据，使用前自行备份。固定补丁版需避免被官方自动升级覆盖。

工作站普通源码启动不自动安装或替换 DeskBox，也不修改开机启动或系统配置。
