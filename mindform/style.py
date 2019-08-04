# coding:utf-8

from collections import OrderedDict, Sequence
import datetime

import pandas as pd

from point import TrendPointPool
from basestyle import Style

LOCAL = False
try:
    from mindgo import log, history
    LOCAL = True
except Exception:
    pass


class Styles(object):
    def __init__(self, driver, follow_stocks, start_date):
        self.start_date = start_date
        self._driver = driver  # 驱动个股

        # 关注的股票
        self._follow_stocks = follow_stocks

        # 注册的形态
        self._styles = None

        # 用户形态数据  {"个股代码": {"形态名": {"字段名": 字段值}}}
        self._style_data = {}
        self._pre_style_data = {}

        # 缓存的所有个股的数据
        self._catch_data = {}

        self.fileds = ['close', 'open', 'low', 'high']

    def _get_all_history_data(self, stock, now):
        start_date = self.start_date

        catched_data = self._catch_data.get(stock)
        if catched_data  is not None:
            catch_start = catched_data.index[0]
            start_date = min(catch_start, self.start_date)

        data = get_price([stock], start_date.strftime("%Y%m%d"), now.strftime("%Y%m%d"), '1d', self.fileds)
        return data.get(stock)

    def regist(self, styles):
        if not self._styles is None:
            raise Exception('只能注册一次形态')
        self._styles = OrderedDict()
        styles = list(set(styles))
        assert len(styles) > 0
        styles = [i if isinstance(i, Style) else i() for i in styles]
        for i in styles:
            assert isinstance(i, Style)
        styles = set(styles)
        while 1:
            if len(styles) == 0:
                break
            hit_style = []
            not_registed_style = []
            not_hited_style = []
            for style in styles:
                style_not_registed_style = []
                style_not_hited_style = []
                for _, depend_style in style.__depends__.items():
                    if depend_style.__name__ in self._styles:  # 已分配
                        continue
                    elif depend_style not in styles: # 未注册
                        style_not_registed_style.append(depend_style)
                    else: # 已注册，但仍未分配，可能该形态太存在依赖
                        style_not_hited_style.append(depend_style)

                not_registed_style += style_not_registed_style
                not_hited_style += style_not_hited_style

                if not (style_not_registed_style or style_not_hited_style):
                    hit_style.append(style)

            if not hit_style and not not_registed_style:
                raise Exception('存在循环依赖{}'.format(styles))
            if hit_style:
                for i in hit_style:
                    styles.remove(i)
                    self._styles[i.__name__] = i
            if not_registed_style:
                for i in not_registed_style:
                    styles.add(i)
        self.__catch_data_num__ = 2
        for style_name, style in self._styles.items():
            if style.__catch_data_num__ > self.__catch_data_num__:
                self.__catch_data_num__ = style.__catch_data_num__

    def _handle_rights(self, stock, now):
        all_history_data = self._get_all_history_data(stock, now)
        catch_k_data = self._catch_data[stock]
        new_catch_k_data = all_history_data.loc[catch_k_data.index[0], :]
        self._catch_data[stock] = new_catch_k_data

        stock_data = self._style_data[stock]
        for style_name, style in self._styles.items():
            # 刷新各字段的数据
            style_data = stock_data[style_name]
            for field_name, field_json_data in style_data.items():
                field = style.__fields__[field_name]
                field.from_json(field_json_data)
                field._handle_rights(all_history_data)
                style_data[field_name] = field.to_json

    def get_all_stocks(self):
        """
        获取所有关注的个股
        :return:
        """
        try:
            return self._follow_stocks()
        except TypeError:
            return self._follow_stocks

    def _handle_rights(self, stock, now):
        all_history_data = self._get_all_history_data(stock, now)
        catch_k_data = self._catch_data[stock]
        new_catch_k_data = all_history_data.loc[catch_k_data.index, :]
        self._catch_data[stock] = new_catch_k_data

        for style_name, style in self._styles.items():
            style.handle_rights()

    def _refresh_stock_data(self, stock, last_two_days_data, now):
        """
        更新个股相关数据，增量更新
        :param stock:
        :param now:
        :return:
        """
        if stock not in self._catch_data:
            self._catch_data[stock] = last_two_days_data
        else:
            catched_k_data = self._catch_data[stock]
            if not last_two_days_data.iloc[0]['close'] == catched_k_data.iloc[-1]['close']:
                self._handle_rights(stock, now)
                catched_k_data = self._catch_data[stock] # 除权后数据已更新，需要重新获取
            if len(catched_k_data) >= self.__catch_data_num__:
                catched_k_data.drop(catched_k_data.index[0:1], inplace=True)
                catched_k_data = catched_k_data.append(last_two_days_data.iloc[1])

    def run(self):
        """
        收盘逐个个股、按照依赖关系逐个计算形态计算数据
        :return:
        """
        all_stocks = self.get_all_stocks()

        # 通过驱动个股获取当天，前一天日期，且认为驱动个股不会停盘
        all_stocks_data = get_candle_stick(all_stocks + [self._driver], get_datetime().strftime("%Y%m%d"),
                                           fre_step="1d", fields=self.fileds,
                                           skip_paused=True, bar_count=2)
        self.yt = all_stocks_data[self._driver].index[0]
        self.td = all_stocks_data[self._driver].index[1]
        log.info("开始计算{}形态数据".format(self.td))
        log.info(all_stocks)

        for stock in all_stocks:
            stock_td_k_data = all_stocks_data.get(stock, None)
            if stock_td_k_data is None:  # 还未上市
                continue

            stock_td = stock_td_k_data.index[-1]
            if not stock_td == self.td:    # 个股当天停盘
                continue

            self._refresh_stock_data(stock, stock_td_k_data, self.td)

        for name in self._styles:
            for stock in all_stocks:
                stock_td_k_data = all_stocks_data.get(stock, None)
                if stock_td_k_data is None:   # 还未上市
                    continue
                stock_td = stock_td_k_data.index[-1]
                stock_yt = stock_td_k_data.index[0]

                # 个股当天停盘
                if not stock_td == self.td:
                    continue

                self._styles[name].handle_data(stock, stock_td, stock_td_k_data.iloc[-1].to_dict())

    def before_trading_start(self, account):
        pass

    def handle_data(self, account, data):
        pass

    def after_trading_end(self, account):
        self.run()


if LOCAL:
    s = Styles('000001', ['600086'])
    s.regist([TrendPointPool])
    while True:
        s.after_trading_end(1)

def init(account):
    # 设置要交易的证券(600519.SH 贵州茅台)
    account.security = '600519.SH'
    s = Styles('000001.SH', ['600086.SH'], datetime.datetime.strptime('20190501', "%Y%m%d"))
    s.regist([TrendPointPool])


def before_trading(account):
    pass


def after_trading(account):
    log.info("after_trading_end:{}".format(get_datetime()))
    account.styles.after_trading_end(account)
    log.info(account.styles._styles['TrendPointPool'].points.get('600089.SH'))


def handle_data(account, data):
    # 获取证券过去20日的收盘价数据
    pass