import requests
import os
from logging import handlers
import logging
from threading import Thread
import time
import sqlite3
from pycqBot.socketApp import cqSocket, asyncHttp
from pycqBot.cqCode import strToCqCodeToDict


class cqHttpApi(asyncHttp):

    def __init__(self, host="http://127.0.0.1:8000", download_path="./download", chunk_size=1024) -> None:
        super().__init__(download_path, chunk_size)
        self.http = host
        self.__reply_list_msg = {}
        self.thread_count = 4
        self.bot_qq = 0

    def create_bot(self, host="ws://127.0.0.1:5700", group_id_list=[], user_id_list=[], options={}):
        """
        直接创建一个 bot 
        """
        return cqBot(
            self, host, group_id_list, user_id_list, options
        )
    
    def _create_sql_link(self, db_path, sleep):
        """
        长效消息存储 初始化
        """
        db_path = os.path.join(db_path, "bot_msg_sql.db")
        self._db_path = db_path

        if os.path.isfile(self._db_path):
            os.remove(self._db_path)

        with sqlite3.connect(self._db_path) as sql_link:
            sql_cursor = sql_link.cursor()
            sql_cursor.execute("""CREATE TABLE `Message` (
                    userId           NOT NULL,
                    stime            NOT NULL,
                    etime            NOT NULL,
                    messageData JSON NOT NULL
                );
            """)
            sql_link.commit()
        
        thread = Thread(target=self._record_message_ck, args=(sleep,),name="_record_message_ck")
        thread.setDaemon(True)
        thread.start()
    
    def _record_message_ck(self, sleep):
        """
        长效消息存储 检查失效消息
        """
        while True:
            try:
                with sqlite3.connect(self._db_path) as sql_link:
                    sql_cursor = sql_link.cursor()
                    data_list = sql_cursor.execute("SELECT * FROM `Message` WHERE etime < '%s'" % int(time.time()))
                    for data in data_list:
                        sql_cursor.execute("DELETE from `Message` where stime = '%s'" % data[1])

            except Exception as err:
                self.recordMessageCKError(err)

            time.sleep(sleep)

    def record_message(self, message_data, time_end):
        """
        长效消息存储
        """
        time_int = int(time.time())
        time_end = time_int + time_end
        try:
            with sqlite3.connect(self._db_path) as sql_link:
                sql_cursor = sql_link.cursor()
                sql_cursor.execute("""
                    INSERT INTO `Message` VALUES (
                        "%s", "%s", "%s", "%s" 
                    )
                """ % (message_data["user_id"], time_int, time_end, message_data))
                sql_link.commit()
        except sqlite3.IntegrityError:
            self.recordMessageInSqlDB(message_data, time_int, time_end)
        except Exception as err:
            self.recordMessageError(message_data, time_int, time_end, err)
    
    def record_message_get(self, user_id):
        """
        长效消息存储 获取
        """
        try:
            with sqlite3.connect(self._db_path) as sql_link:
                sql_cursor = sql_link.cursor()
                data_list = sql_cursor.execute("SELECT * FROM `Message` WHERE userId = '%s'" % user_id)
                return data_list.fetchall()

        except Exception as err:
            self.recordMessageGetError(user_id, err)

    def reply(self, user_id, sleep):
        """
        等待回复
        """
        in_time =  time.time()
        sleep += in_time
        self.__reply_list_msg[user_id] = {}
        while in_time < sleep:
            in_time = time.time()
            if self.__reply_list_msg[user_id] == {}:
                continue
            
            break
        
        reply_msg = self.__reply_list_msg[user_id]
        self.__reply_list_msg.pop(user_id)

        return reply_msg
    
    def _reply_ck(self, user_id):
        """
        等待回复 检查
        """
        if user_id in self.__reply_list_msg:
            return True
        
        return False
    
    def _reply_add(self, user_id, msg):
        """
        等待回复 添加回复数据
        """
        self.__reply_list_msg[user_id] = msg

    def _link(self, api, data={}):
        try:
            with requests.post(self.http + api, data=data) as req:
                json =  req.json()
                logging.debug("cqAPI 响应: %s" % json)
                if json["retcode"] != 0:
                    self.apiLinkError(json)
                    
                return json
            
        except Exception as err:
            self.apiLinkRunError(err)
    
    def send_private_msg(self, user_id, message, group_id="", auto_escape=False):
        """
        发送私聊消息
        """
        post_data = {
            "user_id": user_id,
            "group_id": group_id,
            "message": message,
            "auto_escape": auto_escape
        }
        self.add("/send_msg", post_data)

    def send_group_msg(self, group_id, message, auto_escape=False):
        """
        发送群消息
        """
        post_data = {
            "group_id":group_id,
            "message":message,
            "auto_escape":auto_escape
        }
        self.add("/send_msg", post_data)
    
    def send_group_forward_msg(self, group_id, message):
        """
        发送合并转发 ( 群 )
        """
        post_data = {
            "group_id":group_id,
            "messages": message,
        }
        self.add("/send_group_forward_msg", post_data)

    def send_reply(self, from_message, message, auto_escape=False):
        """
        发送回复
        """
        if from_message["message_type"] == "group":
            self.send_group_msg(from_message["group_id"], message, auto_escape)
        
        if from_message["message_type"] == "private":
            self.send_private_msg(from_message["user_id"], message, auto_escape)
    
    def get_forward(self, forward_id):
        """
        获取合并转发
        """
        post_data = {
            "id":forward_id,
        }
        return self._link("/get_forward_msg", post_data)
    
    def set_group_ban(self, group_id, user_id, duration=30):
        """
        群组单人禁言
        """
        post_data = {
            "group_id":group_id,
            "user_id":user_id,
            "duration":int(duration) * 60
        }
        self.add("/send_msg", post_data)
    
    def set_group_whole_ban(self, group_id, enable=True):
        """
        群组全员禁言
        """
        post_data = {
            "group_id":group_id,
            "enable": enable
        }
        self.add("/send_msg", post_data)
    
    def set_group_admin(self, group_id, user_id, enable=True):
        """
        群组设置管理员
        """
        post_data = {
            "group_id":group_id,
            "user_id": user_id,
            "enable": enable
        }
        self.add("/send_msg", post_data)
    
    def set_group_card(self, group_id, user_id, card=""):
        """
        设置群名片 ( 群备注 )
        """
        post_data = {
            "group_id":group_id,
            "user_id": user_id,
            "card": card
        }
        self.add("/send_msg", post_data)
    
    def set_group_name(self, group_id, group_name):
        """
        设置群名
        """
        post_data = {
            "group_id":group_id,
            "group_name": group_name,
        }
        self.add("/send_msg", post_data)

    def set_group_leave(self, group_id, is_dismiss=False):
        """
        退出群组
        """
        post_data = {
            "group_id":group_id,
            "is_dismiss": is_dismiss,
        }
        self.add("/send_msg", post_data)
    
    def set_group_special_title(self, group_id, user_id, special_title="", duration=-1):
        """
        设置群组专属头衔
        """
        post_data = {
            "group_id":group_id,
            "user_id": user_id,
            "special_title": special_title,
            "duration": duration
        }
        self.add("/send_msg", post_data)

    def set_friend_add_request(self, flag, approve, remark):
        """
        处理加好友请求
        """
        post_data = {
            "flag":flag,
            "approve": approve,
            "remark": remark,
        }
        self.add("/send_msg", post_data)
    
    def set_group_add_request(self, flag, sub_type, approve=True, reason=""):
        """
        处理加群请求／邀请
        """
        post_data = {
            "flag":flag,
            "approve": approve,
            "sub_type": sub_type,
            "reason": reason
        }
        self.add("/send_msg", post_data)
    
    def get_msg(self, message_id):
        """
        获取消息
        """
        post_data = {
            "message_id": message_id,
        }
        return self._link("/get_msg", post_data)
    
    def get_login_info(self):
        """
        获取登录号信息
        """
        return self._link("/set_friend_add_request")
    
    def qidian_get_account_info(self):
        """
        获取企点账号信息
        """
        return self._link("/qidian_get_account_info")
    
    def get_stranger_info(self, user_id, no_cache=False):
        """
        获取陌生人信息
        """
        post_data = {
            "user_id": user_id,
            "no_cache": no_cache
        }
        return self._link("/get_stranger_info", post_data)
    
    def get_friend_list(self):
        """
        获取好友列表
        """
        return self._link("/get_friend_list")
    
    def get_image(self, file):
        """
        获取图片信息
        """
        post_data = {
            "file": file
        }
        return self._link("/get_image", post_data)
    
    async def _cqhttp_download_file(self, url, headers):
        """
        go-cqhttp 的内置下载 (异步)
        """
        post_data = {
            "url":url,
            "headers": headers,
            "thread_count": self.thread_count
        }
        return (await self._asynclink("/download_file", post_data))["data"]["file"]
    
    def cqhttp_download_file(self, url, headers):
        """
        go-cqhttp 的内置下载
        """
        post_data = {
            "url":url,
            "headers": headers,
            "thread_count": self.thread_count
        }
        return self._link("/download_file", post_data)["file"]
    
    def get_status(self):
        """
        获取 go-cqhttp 状态
        """
        return self._link("/get_status")
    
    def recordMessageInSqlDB(self, message_data, time_int, time_end):
        pass
    
    def recordMessageError(self, message_data, time_int, time_end, err):
        logging.error("")
        logging.exception(err)
    
    def recordMessageGetError(self, user_id, err):
        logging.error("")
        logging.exception(err)
    
    def recordMessageCKError(self, err):
        logging.error("")
        logging.exception(err)


class cqBot(cqSocket):
    """
    cqBot 机器人
    """

    def __init__(self, cqapi, host, group_id_list=[], user_id_list=[], options={}):
        super().__init__(host)

        self.cqapi = cqapi
        # bot qq
        self.__bot_qq = 0
        # 需处理群
        self.__group_id_list = group_id_list
        # 需处理私信
        self.__user_id_list = user_id_list
        # 指令列表
        self._commandList = {}
        # 定时任务
        self._timingList = {}
        # 管理员列表
        self.admin = []
        # 指令标志符
        self.commandSign = "#"
        # 帮助信息模版
        self.help_text_format = "本bot帮助信息!\n{help_command_text}\npycqbot v0.1.0"
        self.help_command_text = ""
        # 长效消息存储
        self.messageSql = False
        # 长效消息存储 数据库目录
        self.messageSqlPath = "./"
        # 长效消息存储 清理间隔
        self.messageSqlClearTime = 60

        for key in options.keys():
            if type(options[key]) is str:
                exec("self.%s = '%s'" % (key, options[key]))
            else:
                exec("self.%s = %s" % (key, options[key]))

        """
        内置指令 help
            显示帮助信息
        """

        def print_help(_, __, message, ___):
            self.cqapi.send_reply(message, self.help_text)

        self.command(print_help, "help", {
            "type": "all",
            "help": [
                self.commandSign + "help - 显示本条帮助信息",
            ]
        })

        """
        内置指令 status
            查看 go-cqhttp 状态
        """

        async def _status(message):
            status_info = (await self.cqapi._asynclink("/get_status"))["data"]
            status_msg = "bot (qq=%s) 是否在线：%s\n收到数据包：%s\n发送数据包：%s\n丢失数据包：%s\n接受信息：%s\n发送信息：%s\nTCP 链接断开：%s\n账号掉线次数：%s\n最后消息时间：%s" % (
                self.__bot_qq,
                status_info["online"],
                status_info["stat"]["PacketReceived"],
                status_info["stat"]["PacketSent"],
                status_info["stat"]["PacketLost"],
                status_info["stat"]["MessageReceived"],
                status_info["stat"]["MessageSent"],
                status_info["stat"]["DisconnectTimes"],
                status_info["stat"]["LostTimes"],
                status_info["stat"]["LastMessageTime"],
            )

            self.cqapi.send_reply(message, status_msg)
        
        def status(_, __, message, ___):
            self.cqapi.add_task(_status(message))
        
        self.command(status, "status", {
            "type": "all",
            "admin": True,
            "help": [
                self.commandSign + "status - 获取 go-cqhttp 状态",
            ]
        })
        
    def _check_command_options(self, options):
        """
        检查指令设置
        """
        if "type" not in options:
            options["type"] = "group"
        
        if "admin" not in options:
            options["admin"] = False
        
        if "user" not in options:
            options["user"] = ["all"]
        else:
            options["user"] = options["user"].split(",")
        
        if "ban" not in options:
            options["ban"] = []

        if "help" in options:
            for help_r_text in options["help"]:
                self.help_command_text = "%s%s\n" % (self.help_command_text, help_r_text)
            
            self.help_text = "%s\n" % self.help_text_format.format(help_command_text=self.help_command_text)
        
        return options
    
    def _check_timing_options(self, options, timing_name):
        options["name"] = timing_name

        if "timeSleep" not in options:
            logging.warning("定时任务 %s 没有指定 timeSleep 间隔, 中止创建" % timing_name)
            return False

        if "ban" not in options:
            options["ban"] = []

        return options
        
    def command(self, function, command_name, options=None):
        if options is None:
            options = {}
            
        options = self._check_command_options(options)

        if type(command_name) == str:
            command_name = [command_name]

        for name in command_name:
            self._commandList[name] = options
            self._commandList[name]["function"] = function

    def _timing_job(self, job):
        run_count = 0
        while True:
            self.timing_jobs_start(job, run_count)
            for group_id in self.__group_id_list:
                if group_id in job["ban"]:
                    return
                
                run_count += 1
                try:
                    job["function"](group_id)
                    self.timing_job_end(job, run_count, group_id)

                except Exception as err:
                    self.runTimingError(job, run_count, err, group_id)

            self.timing_jobs_end(job, run_count)
            time.sleep(job["timeSleep"])
    
    def timing(self, function, timing_name, options=None):
        if options is None:
            options = {}

        options = self._check_timing_options(options, timing_name)
        if not options:
            return

        options["function"] = function
        self._timingList[timing_name] = options

        thread = Thread(target=self._timing_job, args=(self._timingList[timing_name],), name=timing_name)
        thread.setDaemon(True)
        thread.start()

        logging.info("创建定时任务 %s " % timing_name)
    
    def _meta_event_connect(self, message):
        """
        连接响应
        """
        self.__bot_qq = message["self_id"]
        self.cqapi.bot_qq = message["self_id"]
        if self.messageSql is True:
            self.cqapi._create_sql_link(self.messageSqlPath, self.messageSqlClearTime)
    
    def meta_event_connect(self, message):
        """
        连接响应
        """
        self._meta_event_connect(message)
        logging.info("成功连接 websocket 服务! bot qq:%s" % self.__bot_qq)
    
    def timing_start(self):
        """
        启动定时任务
        """
        self._timing_start()
        logging.info("定时任务启动完成!")
    
    def timing_jobs_start(self, job, run_count):
        """
        群列表定时任准备执行
        """
        pass
    
    def timing_job_end(self, job, run_count, group_id):
        """
        定时任务被执行
        """
        pass

    def timing_jobs_end(self, job, run_count):
        """
        群列表定时任务执行完成
        """
        logging.debug("定时任务 %s 执行完成! 共执行 %s 次" % (job["name"], run_count))
        pass
    
    def runTimingError(self, job, run_count, err, group_id):
        """
        定时任务执行错误
        """
        logging.error("定时任务 %s 在群 %s 执行错误... 共执行 %s 次 Error: %s" % (job["name"], group_id, run_count, err))
        logging.exception(err)

    def user_log_srt(self, message):
        user_id = message["user_id"]
        if message["message_type"] == "private":
            user_name = message["sender"]["nickname"]
        elif message["message_type"] == "group":
            if message["anonymous"] == None:
                if message["sender"]["card"].strip() != '':
                    user_name = message["sender"]["card"]
                else:
                    user_name = message["sender"]["nickname"]
            else:
                user_name = "匿名用户 - %s flag: %s" % (message["anonymous"]["name"],
                    message["anonymous"]["flag"])

        if "group_id" in message:
            return "%s (qq=%s,群号=%s)" % (user_name, user_id, message["group_id"])

        return "%s (qq=%s)" % (user_name, user_id)

    def _set_command_key(self, message):
        """
        指令解析
        """

        commandSign = list(message)[0]
        command_str_list = message.split(" ")
        command = command_str_list[0].lstrip(commandSign)
        commandData = command_str_list[1:]

        return commandSign, command, commandData
    
    def _check_command(self, message, command_type):
        """
        指令检查
        """

        commandSign, command, commandData = self._set_command_key(message["message"])

        if commandSign != self.commandSign:
            return False
        
        if "group_id" in message:
            from_id = message["group_id"]
        else:
            from_id = message["user_id"]

        if command not in self._commandList:
            self.notCommandError(message, from_id)
            return False

        if self._commandList[command]["type"] != command_type and self._commandList[command]["type"] != "all":
            return False
        
        self.check_command(message, from_id)
        
        if from_id in self._commandList[command]["ban"]:
            self.banCommandError(message, from_id)
            return False
        
        user_list = self._commandList[command]["user"]
        if user_list[0] != "all" and message["message_type"] == "group":
            if "role" not in message["sender"] and "anonymous" not in user_list:
                self.userPurviewError(message, from_id)
                return False
            elif "role" in message["sender"]:
                if message["sender"]["role"] not in user_list["user"] and user_list[0] != "nall":
                    self.userPurviewError(message, from_id)
                    return False
        
        if self._commandList[command]["admin"] and message["user_id"] not in self.admin:
            self.purviewError(message, from_id)
            return False

        return commandSign, command, commandData, from_id
    
    def _run_command(self, message, cqCode_list, command_type):
        """
        指令运行
        """
        def run_command(message, cqCode_list, command_type):
            try:
                commandIn = self._check_command(message, command_type)
                if not commandIn:
                    return

                commandSign, command, commandData, from_id = commandIn
                self._commandList[command]["function"](commandData, cqCode_list, message, from_id)

            except Exception as err:
                self.runCommandError(message, err, from_id)
        
        thread = Thread(target=run_command, args=(message, cqCode_list, command_type, ), name="command")
        thread.setDaemon(True)
        thread.start()
        
    def _run_record_command(self, record, message, cqCode_list):
        try:
            logging.info("%s 运行记录指令: %s: %s" % (self.user_log_srt(message), record["record_message"]["message"], message["message"]))
            self._commandList[record["record_command"]]["backFunction"](message, record, cqCode_list)
        except Exception as err:
            self.runRecordCommandError(record, err)
    
    def check_command(self, message, from_id):
        """
        指令开始检查勾子
        """
        logging.info("%s 使用指令: %s" % (self.user_log_srt(message), message["message"]))

    def on_group_msg(self, message, cqCode_list):
        pass
    
    def on_private_msg(self, message, cqCode_list):
        pass
    
    def _message(self, message):
        """
        通用消息处理
        """

        # 解析 cqCode
        cqCode_list = strToCqCodeToDict(message["message"])
        # 检查等待回复
        if self.cqapi._reply_ck(message["user_id"]):
            self.cqapi._reply_add(message["user_id"], message)
        
        return cqCode_list

    def _message_private(self, message):
        """
        通用私聊消息处理
        """
        if (message["user_id"] not in self.__user_id_list) and self.__user_id_list != []:
            return

        cqCode_list = self._message(message)
        self.on_private_msg(message, cqCode_list)
        self._run_command(message, cqCode_list, "private")
    
    def _message_group(self, message):
        """
        通用群消息处理
        """
        if message["group_id"] not in self.__group_id_list and self.__group_id_list != []:
            return

        cqCode_list = self._message(message)
        self.on_group_msg(message, cqCode_list)
        for cqCode in cqCode_list:
            if cqCode["type"] == "at":
                if cqCode["data"]["qq"] == str(self.__bot_qq):
                    self.at_bot(message, cqCode_list, cqCode)
                    continue
                
                self.at(message, cqCode_list, cqCode)
        
        self._run_command(message, cqCode_list, "group")
    
    def _bot_message_log(self, log, message):
        logging.info(log)
        self.cqapi.send_reply(message, log)
    
    def at_bot(self, message, cqCode_list, cqCode):
        """
        接收到 at bot
        """
        logging.info("接收到 at bot %s " % self.user_log_srt(message))
    
    def at(self, message, cqCode_list, cqCode):
        """
        接收到 at
        """
        pass

    def message_private_friend(self, message):
        """
        好友私聊消息
        """
        self._message_private(message)
    
    def message_private_group(self, message):
        """
        群临时会话私聊消息
        """
        self._message_private(message)
    
    def message_private_group_self(self, message):
        """
        群中自身私聊消息
        """
        self._message_private(message)
    
    def message_private_other(self, message):
        """
        私聊消息
        """
        self._message_private(message)

    def message_group_normal(self, message):
        """
        群消息
        """
        self._message_group(message)
    
    def notCommandError(self, message, from_id):
        """
        指令不存在时错误
        """
        self._bot_message_log("指令 %s 不存在..." % message["message"], message)
    
    def banCommandError(self, message, from_id):
        """
        指令被禁用时错误
        """
        self._bot_message_log("指令 %s 被禁用!" % message["message"], message)
    
    def userPurviewError(self, message, from_id):
        """
        指令用户组权限不足时错误
        """
        self._bot_message_log("%s 用户组权限不足... 指令 %s" % (self.user_log_srt(message), message["message"]), message)
    
    def purviewError(self, message, from_id):
        """
        指令权限不足时错误 (bot admin)
        """
        self._bot_message_log("%s 权限不足... 指令 %s" % (self.user_log_srt(message), message["message"]), message)
    
    def runCommandError(self, message, err, from_id):
        """
        指令运行时错误
        """
        self._bot_message_log("指令 %s 运行时错误... Error: %s" % (message["message"], err), message)
        logging.exception(err)
    

    def notice_group_upload(self, message):
        """
        群文件上传
        """
        pass
    
    def notice_group_admin_set(self, message):
        """
        群管理员设置
        """
        pass

    def notice_group_admin_unset(self, message):
        """
        群管理员取消
        """
        pass
    
    def notice_group_decrease_leave(self, message):
        """
        群成员减少 - 主动退群
        """
        pass
    
    def notice_group_decrease_kick(self, message):
        """
        群成员减少 - 成员被踢
        """
        pass
    
    def notice_group_decrease_kickme(self, message):
        """
        群成员减少 - 登录号被踢
        """
        pass
    
    def notice_group_increase_approve(self, message):
        """
        群成员增加 - 同意入群
        """
        pass

    def notice_group_increase_invite(self, message):
        """
        群成员增加 - 邀请入群
        """
        pass
    
    def notice_group_ban_ban(self, message):
        """
        群禁言
        """
        pass

    def notice_group_ban_lift_ban(self, message):
        """
        群解除禁言
        """
        pass

    def notice_group_recall(self, message):
        """
        群消息撤回
        """
        pass
    
    def notice_notify_lucky_king(self, message):
        """
        群红包运气王提示
        """
        pass
    
    def notice_notify_honor(self, message):
        """
        群成员荣誉变更提示
        honor_type 荣誉类型

        talkative:龙王 
        performer:群聊之火 
        emotion:快乐源泉
        """

        pass
    
    def notice_group_card(self, message):
        """
        群成员名片更新
        """
        pass
    
    def notice_friend_add(self, message):
        """
        好友添加
        """
        pass

    def notice_friend_recall(self, message):
        """
        好友消息撤回
        """
        pass
    
    def notice_notify_poke(self, message):
        """
        好友/群内 戳一戳
        """
        pass
    
    def notice_offline_file(self, message):
        """
        接收到离线文件
        """
        pass

    def notice_client_status(self, message):
        """
        其他客户端在线状态变更
        """
        pass
    
    def notice_essence_add(self, message):
        """
        精华消息添加
        """
        pass
    
    def notice_essence_delete(self, message):
        """
        精华消息移出
        """
        pass

    def request_friend(self, message):
        """
        加好友请求
        """
        pass

    def request_group_add(self, message):
        """
        加群请求
        """
        pass
    
    def request_group_invite(self, message):
        """
        加群邀请
        """
        pass


class cqLog:

    def __init__(self, level=logging.DEBUG, 
            logPath="./cqLogs", 
            when="d", 
            interval=1,
            backupCount=7
        ):

        logger = logging.getLogger()
        logger.setLevel(level)

        if not os.path.isdir(logPath):
            os.makedirs(logPath)

        sh = logging.StreamHandler()
        rh = handlers.TimedRotatingFileHandler(
            os.path.join(logPath, "cq.log"), 
            when,
            interval,
            backupCount
        )
        
        logger.addHandler(sh)
        logger.addHandler(rh)

        formatter = logging.Formatter(
            self.setFormat()
        )
        sh.setFormatter(formatter)
        rh.setFormatter(formatter)
        
    def setFormat(self):
        return "[%(asctime)s][%(threadName)s][%(levelname)s] PyCqBot: %(message)s"