# IPS3608 Codex Bridge

面向 FNIRSI IPS3608 的本机常驻安全桥接服务。它只提供输出开、输出关和状态读取，不实现电压、电流设定。

> [!WARNING]
> 本版本不能读取或限制面板上预设的电压、电流，也没有权限令牌和输出空闲看门狗。使用前必须人工核对面板设定；程序在 `on` 后崩溃可能导致输出继续保持开启。要求策略限值、鉴权和自动关断时，请改用同级目录中的 `IPS3608-Codex-Automation`。

实体测试结果和完整警告见 [docs/HARDWARE-TEST-2026-07-21.md](docs/HARDWARE-TEST-2026-07-21.md)。

如果出现串口短写、Windows 错误 995 或错误 31，请停止服务并更换数据线或 USB 物理端口。若 `off` 无法验证 0V，必须把输出视为未知并手动关断电源。

## 为什么需要常驻服务

一次性脚本通常会为每条命令重复执行“打开串口 → 进入 PC 模式 → 操作 → 断开”。部分 IPS3608/Windows `usbser` 组合在频繁连接后会出现写超时、无响应或面板长期锁定。

本项目只打开一次串口，并在后台保持会话：

```text
Codex / 测试脚本
        │ localhost JSON
        ▼
IPS3608 Codex Bridge（常驻）
        │ 单一、持续的串口会话
        ▼
FNIRSI IPS3608
```

多个项目或同一 Codex 话题中的多次命令都会复用同一连接。执行 `stop` 后，服务先尝试关闭输出，再退出 PC 模式并释放串口。

## 安全边界

公开命令白名单只有：

- `health`：查看服务和串口状态；
- `status`：读取电压、电流、功率和温度；
- `on`：开启输出；
- `off`：关闭输出；
- `start` / `stop`：启动或安全停止本机服务；
- `ports`：列出串口。

代码中没有电压、电流写入命令，也不提供原始串口透传。电压和限流必须由人工在电源面板上预先设定并确认。

`on` 只有在回读电压高于 0.1V 后才会成功，`off` 只有在回读电压不高于 0.1V 后才会成功。该检查只能确认实际开关状态，不能判断人工设置的电压、电流是否安全。

这属于 API 安全边界，不是针对拥有本机串口访问权限的恶意程序的操作系统沙箱。

## Windows 快速开始

```powershell
.\install.ps1
.\ips3608.cmd start
.\ips3608.cmd health
.\ips3608.cmd status
.\ips3608.cmd on
.\ips3608.cmd off
.\ips3608.cmd stop
```

`on`/`off` 会在内部等待并验证实际电压。默认轮询间隔为 5 秒，以降低 IPS3608 USB CDC 写超时概率。

默认设备为 `COM3`，本机服务监听 `127.0.0.1:36080`。首次启动时可以指定其他串口：

```powershell
.\ips3608.cmd start --device-port COM5
```

必须显式执行 `start`。`status/on/off/health` 在服务未运行或无响应时只会报错，绝不会隐式启动第二个服务。

## Codex 项目接入

把 [AGENTS.example.md](AGENTS.example.md) 中的内容复制到目标项目的 `AGENTS.md`，并把控制器路径改成此仓库中 `ips3608.cmd` 的绝对路径。

推荐的测试结构：

```powershell
$psu = "C:\path\to\IPS3608-Codex-Bridge\ips3608.cmd"

& $psu status
try {
    & $psu on
    # 烧录、日志采集和测试
}
finally {
    & $psu off
}
```

服务会继续运行并保持串口连接；整个调试话题结束后再执行 `stop`。

## 开发

```powershell
.\.venv\Scripts\python.exe -m pytest
.\ips3608.cmd start --simulate
.\ips3608.cmd status
.\ips3608.cmd stop
```

协议范围与设计说明见 [docs/PROTOCOL.md](docs/PROTOCOL.md) 和 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 参考资料与致谢

协议行为参考了公开资料及以下项目：

- `daktari77/FNIRSI-IPS3608`；
- `cho45/fnirsi-dps-150`；
- FNIRSI IPS3608 用户手册和官方 PC 软件说明。

FNIRSI 和 IPS3608 是其各自权利人的商标。本项目与 FNIRSI 官方无隶属关系。

## License

MIT
