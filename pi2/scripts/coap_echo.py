import asyncio
import aiocoap
import aiocoap.resource as resource


class Echo(resource.Resource):
    async def render_post(self, request):
        return aiocoap.Message(
            code=aiocoap.CHANGED,
            payload=request.payload
        )


async def main():
    root = resource.Site()
    root.add_resource(["echo"], Echo())

    await aiocoap.Context.create_server_context(
        root,
        bind=("0.0.0.0", 5683)
    )

    print("CoAP echo server running on port 5683", flush=True)

    await asyncio.get_running_loop().create_future()


asyncio.run(main())
