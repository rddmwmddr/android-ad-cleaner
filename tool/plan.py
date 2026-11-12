"""一次执行要跑哪些步骤：八个键、各自的默认值、结构不变量，以及与 JSON 的双向转换。

这份形状以前只活在 `Dispatcher.start` 的参数说明与 `plan_tasks` 的取值里，加一个键要靠两处手写
碰巧一致。沿用 #1102 的做法，现在它在这里定义一次。消费方是客户端的执行侧（`gui/app.py`）：
前端 JSON 在 `Api.start()` 收成它，之后排任务、重试轮与一次执行的状态都传对象（#1106）；
两个前端发来的 JSON 形状不变。
"""
import dataclasses
from typing import Any, get_origin, get_type_hints


@dataclasses.dataclass
class Plan:
    """这次执行跑哪些步骤。

    默认构造是「首次执行」：快照与收尾默认开启，其余为空。重试轮的默认相反（只重跑上一轮真没做成
    的那几步），由重试侧逐键显式给出，不依赖无参构造——这条不对称是刻意的，别当成 bug 修掉。
    `model` 是旁路字段：只给 `Job.model` 与上报带上机型，不参与任务派生。
    两个前端只发其中七个键，`finish` 由服务端默认补上。
    """

    backup: bool = True
    model: str = ""
    steps: list[str] = dataclasses.field(default_factory=list)
    ref: bool = False
    channels: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    quickapp: bool = False
    ads: list[str] = dataclasses.field(default_factory=list)
    finish: bool = True

    def __post_init__(self) -> None:
        # 结构不变量落在这里而不是 from_json：直接构造与 JSON 两条路进来的值都收成声明形状。
        # 形状取自 get_type_hints：dataclass 的 field.type 在延迟注解下是字符串，认不出 bool / list。
        for name, shape in get_type_hints(type(self)).items():
            setattr(self, name, _coerce(getattr(self, name), shape))

    @classmethod
    def from_json(cls, data: "Plan | dict[str, Any]") -> "Plan":
        """JSON → `Plan`。缺的键取默认，不认识的键忽略。

        传进来的已经是 `Plan` 就原样返回（幂等），内部传对象时不必在边界来回转 dict。
        """
        if isinstance(data, Plan):
            return data
        return cls(**{f.name: data[f.name] for f in dataclasses.fields(cls) if f.name in data})

    def to_json(self) -> dict[str, Any]:
        """与 `from_json` 往返相等：`from_json(p.to_json()) == p`。"""
        return dataclasses.asdict(self)

    def __getitem__(self, name: str) -> Any:
        """按字段名读：`p["steps"]` 与 `p.steps` 同义。

        生产代码一律用属性；留着下标读法是为了既有用例——`retry_plan()` 的返回从字典换成对象时，
        照旧拿 `plan["steps"]` 断言的用例不用改写（#1106）。它只实现按名字读这一半，`in` 与迭代
        不跟着变成字典语义。
        """
        if name not in {f.name for f in dataclasses.fields(self)}:
            raise KeyError(name)
        return getattr(self, name)


def _coerce(value: Any, shape: Any) -> Any:
    """按声明形状收拢：bool 收成真假，str 收成文本，list[...] 只收列表。

    列表字段不把字符串拆成字符：`steps="桌面"` 是输入形状错了，静默拆成「桌」「面」会排出一串
    假段名、在真机上逐个失败，收成空列表更能说明问题。
    """
    if shape is bool:
        return bool(value)
    if shape is str:
        return "" if value is None else str(value)
    if get_origin(shape) is list:
        return list(value) if isinstance(value, (list, tuple)) else []
    return value
