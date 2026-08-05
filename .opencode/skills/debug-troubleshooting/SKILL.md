---
name: debug-troubleshooting
description: 软件调试与排错技能，覆盖Python代码调试、环境依赖问题、打包报错、运行时异常的系统排查方法。包含错误信息解读、日志分析、复现定位、根因分析的完整方法论。使用场景：Python报错排查、依赖冲突解决、PyInstaller打包排错、环境配置问题、性能问题定位、bug系统排查。
---

# 软件调试与排错技能

## 排错核心方法论

### 四步排错法
1. **复现**：稳定复现问题，记录触发条件
2. **定位**：缩小范围，找到出问题的代码行/模块
3. **分析**：理解为什么会出错，找到根因
4. **验证**：修复后验证，确保不引入新问题

### 黄金法则
- **不要猜**：用日志和调试器确认
- **二分法**：每次排除一半可能性
- **对比法**：能跑的版本和不能跑的版本对比
- **最小化**：剥离无关代码，用最小的例子复现

## 错误信息解读（Python）

### 看懂 Traceback
从下往上看：
1. 最下面：错误类型 + 错误信息
2. 往上：出错的具体位置（文件+行号+函数）
3. 再往上：调用链

### 常见错误速查
| 错误类型 | 原因 | 排查方向 |
|----------|------|----------|
| NameError | 变量名没定义 | 拼写错误、作用域、没import |
| TypeError | 类型不对 | 字符串当数字用、None参与运算 |
| ValueError | 值不对 | int('abc')、空列表取max |
| IndexError | 索引越界 | 列表下标超长度、空列表[0] |
| KeyError | 字典键不存在 | 用 .get(key, default) |
| AttributeError | 对象没有这个属性 | None.xxx()、类型判断错了 |
| ImportError | 导入失败 | 没装包、包名写错、路径不对 |
| FileNotFoundError | 文件不存在 | 路径写错、相对路径基准不对 |
| PermissionError | 权限不够 | 文件被占用、写入系统目录 |

## 调试工具与方法

### 1. print 调试（最快上手）
```python
def calculate(items):
    print(f"DEBUG: items = {items}, len = {len(items)}")
    return sum(items) / len(items)
```

### 2. logging 日志（推荐）
```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)
```

### 3. 断点调试（最强）
- VS Code 断点：F5启动，F10单步，F11进入函数
- pdb 命令行：import pdb; pdb.set_trace()

## 环境依赖问题排查

### ModuleNotFoundError
1. 确认包装了没：pip list | grep 包名
2. 确认装到了哪个环境：which python
3. 确认当前运行的 python 和 pip 是不是同一个环境
4. 虚拟环境有没有激活
5. 包名是不是写错了

### 依赖冲突
- 用虚拟环境，每个项目独立
- requirements.txt 锁定版本
- pip check 检查冲突

## PyInstaller 打包排错

### 常见报错
1. **ImportError: No module named 'xxx'**
   - 原因：动态导入检测不到
   - 解决：--hidden-import=xxx

2. **打包后找不到文件**
   - 原因：相对路径基准变了
   - 解决：用 sys._MEIPASS + --add-data

3. **exe 体积超大**
   - 用虚拟环境，只装必要的包
   - --exclude-module 排除不用的大库
   - UPX 压缩

### 调试技巧
1. 先不打单文件，打包成文件夹看缺什么
2. 带控制台运行，不用 --windowed，能看到报错
3. --debug all 加调试参数

## 性能问题定位

### 找瓶颈
```python
import time

def benchmark(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f"{func.__name__} 耗时: {elapsed:.3f}s")
        return result
    return wrapper
```

### 更专业：cProfile
```bash
python -m cProfile -s cumulative your_script.py
```

## 二分法定位 bug
1. 注释掉一半代码，看还报错吗
2. 如果还报错 → 问题在剩下的一半
3. 如果不报错了 → 问题在注释掉的那一半
4. 继续对半切，直到定位到具体行

## 搜索报错的正确姿势
1. 把报错的核心信息复制出来
2. 加引号精确搜索
3. 加上技术栈关键词
4. 优先看 Stack Overflow、GitHub Issues

## 参考资料

