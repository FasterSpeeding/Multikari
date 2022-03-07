class Foo:
    @property
    def foo(self) -> int:
        return 1



class Bar(Foo):
    foo: int
