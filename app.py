import gradio as gr


def greet(name):
    return "Hello " + name + "!"


# 创建并启动界面
demo = gr.Interface(fn=greet, inputs="text", outputs="text")
demo.launch()
