from decimal import Decimal, ROUND_HALF_UP


def check(read, expect):
    # 去除输入和输出的空格
    read_str = read.strip()
    expect_str = expect.strip()

    # 检查选手输出是否为空
    if not read_str:
        return "WA"

    # 检查选手输出是否包含非法字符（只允许数字和小数点）
    if any(char not in '0123456789.' for char in read_str):
        return "WA"

    # 检查选手输出中是否包含多个小数点
    if read_str.count('.') > 1:
        return "WA"

    # 计算选手输出的总位数（数字字符个数）
    total_digits = sum(char.isdigit() for char in read_str)
    if total_digits == 0:
        return "WA"
    if total_digits > 10:
        return "WA"

    # 将选手输出转换为 Decimal 类型
    try:
        if read_str.startswith('.'):
            read_str = '0' + read_str  # 处理以小数点开头的情况，如 ".123" -> "0.123"
        if read_str.endswith('.'):
            read_str = read_str[:-1]  # 处理以小数点结尾的情况，如 "123." -> "123"
        x = Decimal(read_str)
    except:
        return "WA"

    # 检查选手输出是否为负数（题目要求非负）
    if x < 0:
        return "WA"

    # 确定输入 a 的小数位数
    if '.' in expect_str:
        n = len(expect_str.split('.')[1])  # 小数部分位数
    else:
        n = 0  # 无小数部分

    # 构造四舍五入的量化器
    if n > 0:
        quantizer = Decimal('0.' + '0' * n)
    else:
        quantizer = Decimal('1')  # 舍入到整数

    # 执行四舍五入（ROUND_HALF_UP 表示数学四舍五入）
    try:
        rounded_x = x.quantize(quantizer, rounding=ROUND_HALF_UP)
    except:
        return "WA"

    # 格式化四舍五入后的结果，使其小数位数与 a 相同
    if n == 0:
        s_rounded = str(rounded_x).split('.')[0]  # 无小数部分，取整数部分
    else:
        parts = str(rounded_x).split('.')
        integer_part = parts[0] if len(parts) > 0 else '0'
        fractional_part = parts[1] if len(parts) > 1 else ''
        fractional_part = fractional_part.ljust(n, '0')[:n]  # 补零或截断至 n 位
        s_rounded = integer_part + '.' + fractional_part

    # 比较格式化后的结果与输入 a
    if s_rounded == expect_str:
        return "AC"
    else:
        return f"WA"
