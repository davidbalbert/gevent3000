cdef extern from "libevent.h":
    struct evbuffer:
        char *buf "buffer"
        int off

    evbuffer *evbuffer_new()
    int       evbuffer_add(evbuffer *buf, char *p, int len)
    char     *evbuffer_readline(evbuffer *buf)
    void      evbuffer_free(evbuffer *buf)
    size_t    evbuffer_get_length(evbuffer *buffer)
    unsigned char *evbuffer_pullup(evbuffer *buf, size_t size)
    int       EVBUFFER_DRAIN(evbuffer *buf, size_t len)


cdef class buffer:
    cdef evbuffer* __obj

    def __init__(self, size_t _obj):
        self.__obj = <evbuffer*>_obj

    property _obj:

        def __get__(self):
            return <size_t>(self.__obj)

    def __len__(self):
        return evbuffer_get_length(self.__obj)

    def __nonzero__(self):
        return self.__obj and evbuffer_get_length(self.__obj)

    # cython does not implement generators
    #def __iter__(self):
    #    while len(self):
    #        yield self.readline()

    def read(self, long size=-1):
        cdef long length = evbuffer_get_length(self.__obj)
        if size < 0:
            size = length
        else:
            size = min(size, length)
        if size <= 0:
            return ''
        cdef char* data = <char*>evbuffer_pullup(self.__obj, size)
        if not data:
            raise RuntimeError('evbuffer_pullup(%x, %s) returned NULL' % (self._obj, size))
        cdef object result = PyString_FromStringAndSize(data, size)
        cdef res = EVBUFFER_DRAIN(self.__obj, size)
        if res:
            raise RuntimeError('evbuffer_drain(%x, %s) returned %s' % (self._obj, size, res))
        return result

    def readline(self):
        cdef char* res = evbuffer_readline(self.__obj)
        if res:
            return res
        return ''

    def readlines(self, hint=-1):
        return list(self.__iter__())

 
