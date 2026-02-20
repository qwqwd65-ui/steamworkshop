# Fan Workshop Downloader (Python)

一个基于 `catalogue.smods.ru` + `modsbase` 的创意工坊下载工具（命令行 / 菜单模式）。

## 功能

- 全局关键词搜索（不限制游戏）
- 指定游戏搜索（支持 `AppId` / 游戏名 / slug）
- 批量任务（关键词文件，一行一个）
- 多线程并发处理
- 超时可配置
- 下载时显示进度、速度与预计剩余时间（ETA）
- 默认下载目录为当前用户 `Downloads`
- 支持游戏缓存（`games-cache.json`）
- 菜单大标题支持 FIGlet 字体

## 环境

- Python 3.9+

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 1) 菜单模式（推荐）

```bash
python workshop_downloader.py
```

> 无参数时自动进入菜单。

### 2) 命令行模式

#### 全局搜索（中文/英文关键词都可）

```bash
python workshop_downloader.py --keyword "Omaha Beach V3.0" --only-get-link
```

#### 指定游戏搜索

```bash
python workshop_downloader.py --game ravenfield --keyword "Omaha Beach V3.0"
```

#### 批量下载（每行一个关键词）

```bash
python workshop_downloader.py --list-file keywords.txt --workers 4 --timeout 30
```

#### 列出支持游戏

```bash
python workshop_downloader.py --list-games
```

#### 刷新支持游戏缓存

```bash
python workshop_downloader.py --refresh-games-cache
```

## 配置文件

首次运行后会在项目目录生成 `py-config.json`，支持：

- `download_dir`：下载目录
- `workers`：线程数（1-16）
- `timeout`：超时秒数（5-180）
- `banner_font`：FIGlet 字体（如 `ansi_shadow`, `big`, `slant`）

## 打包 EXE（Windows）

### 一键打包

```bat
build.bat
```

打包输出：

- `dist/FanWorkshopDL.exe`

可选自定义图标：

- 在项目目录放 `app.ico`，`build.bat` 会自动带上。

## 注意

- 该项目仅供学习交流，请遵守相关平台规则与法律。
- 必须尽量使用地图/模组全称进行搜索，否则不保证输出可靠。
- 站点结构变更可能导致解析失败，需要调整正则或流程。
