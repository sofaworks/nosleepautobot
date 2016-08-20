from apscheduler.schedulers.blocking import BlockingScheduler

sched = BlockingScheduler()

@sched.scheduled_job('interval', minutes=3)
def timed_job():
    print("Running the bot every 3 minutes.")
