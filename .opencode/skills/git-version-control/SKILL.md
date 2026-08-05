---
name: git-version-control
description: Git版本控制技能，含基础工作流、分支管理、冲突解决、坚果云+Git混合协同方案。使用场景：代码版本管理、多人协作、分支开发、代码回退、跨设备同步。
---

# Git版本控制技能

## 基础工作流

### 常用命令
```bash
# 初始化仓库
git init

# 查看状态
git status

# 添加文件
git add .
git add filename.py

# 提交
git commit -m "提交信息"

# 查看历史
git log
git log --oneline --graph
```

### 提交信息规范
```
<type>: <subject>

类型：
- feat: 新功能
- fix: 修复bug
- docs: 文档
- style: 格式（不影响代码运行）
- refactor: 重构
- test: 测试
- chore: 构建/工具
```

## 分支管理

### 基础分支操作
```bash
# 创建分支
git branch dev

# 切换分支
git checkout dev
# 或
git switch dev

# 创建并切换
git checkout -b feature-xxx

# 合并分支
git merge dev

# 删除分支
git branch -d feature-xxx
```

### 推荐工作流
- **main/master**：主分支，稳定可发布
- **dev**：开发分支，日常开发在这
- **feature-xxx**：功能分支，开发新功能
- **hotfix-xxx**：紧急修复分支

## 远程仓库

### 常用操作
```bash
# 添加远程仓库
git remote add origin https://github.com/xxx/xxx.git

# 推送
git push origin main

# 拉取
git pull origin main

# 克隆
git clone https://github.com/xxx/xxx.git
```

### 国内加速
```bash
# 全局配置代理
git config --global url."https://ghproxy.com/https://github.com".insteadOf "https://github.com"

# 取消代理
git config --global --unset url."https://ghproxy.com/https://github.com".insteadOf
```

## 冲突解决

### 常见冲突场景
1. 同一文件同一行被不同人修改
2. 一个人删了文件，另一个人改了文件
3. 二进制文件冲突（无法手动合并）

### 解决步骤
1. `git status` 看哪些文件冲突
2. 打开冲突文件，找 <<<<<<< 标记
3. 手动选择保留哪部分
4. `git add 文件名` 标记已解决
5. `git commit` 完成合并

## 坚果云 + Git 混合协同方案

### 适用场景
- 多设备（台式机+笔记本）同步
- 不想搭私有Git服务器
- 坚果云已经在用

### 方案
- 代码用 Git 管理版本
- 整个项目文件夹放在坚果云里同步
- 每台设备各自提交，坚果云同步文件
- 注意：.git 目录也会同步，一般没问题

### 注意事项
- 不要两台设备同时改同一个文件
- 改完记得 commit 再换设备
- 定期检查 git status，确保干净

## 后悔药（回退操作）

### 改了还没 add
```bash
# 放弃所有修改
git checkout .
# 放弃单个文件
git checkout filename.py
```

### add 了还没 commit
```bash
# 取消 add
git reset HEAD .
# 然后再 checkout 放弃修改
```

### 已经 commit 了
```bash
# 回退到上一个提交，保留修改
git reset --soft HEAD~1

# 回退到上一个提交，放弃修改（危险）
git reset --hard HEAD~1
```

### 已经 push 了
```bash
# 反向提交（推荐，不修改历史）
git revert HEAD

# 强制推送（危险，会改历史）
git push -f
```

## 参考资料

