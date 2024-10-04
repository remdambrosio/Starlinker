#
# Title: NicknamePackage.py
# Authors: Rem D'Ambrosio
# Created: 2024-08-22
# Description: stores Starlink device info and recommends a suitable Starlink API nickname
#

class NicknamePackage:

    def __init__(self,
                 cur_nick: str = '',
                 sln: str = '',
                 kit: str = '',
                 adr: str = '', 

                 cur_nick_router: str = '',
                 cur_nick_site: str = '',

                 location_router: str = '',
                 location_site: str = '',

                 rec_nick: str = '',
                 note: str = '',
                 updated: bool = False,
                 
                 name_src: str = 'none',
                 router_src: str = 'none',
                 result: str = 'cannot update'):
        
        self.cur_nick = cur_nick
        self.sln = sln
        self.kit = kit
        self.adr = adr

        self.cur_nick_router = cur_nick_router
        self.cur_nick_site = cur_nick_site

        self.location_router = location_router
        self.location_site = location_site

        self.rec_nick = rec_nick
        self.note = note
        self.updated = updated
    
        self.name_src = name_src
        self.router_src = router_src
        self.result = result


    def recommend_nickname(self):
        """
        Populates self.rec_nick based on info found via current nickname; if none/not verified, then try lat/lon
        """
        site = ''
        router = ''

        if self.cur_nick_site:
            site = self.cur_nick_site
        elif self.location_site:
            site = self.location_site

        if self.cur_nick_router:
            router = self.cur_nick_router
            self.router_src = 'current nickname'
        elif self.location_router:
            router = self.location_router
            self.router_src = 'geolocation'
        
        if site and router and self.kit:
            self.rec_nick = f'{self.kit}-SK{router}-{site}'
            self.result = 'can update'
        else:
            self.router_src = 'none'
            self.set_note()

        if self.rec_nick == self.cur_nick:
            self.note += 'current nickname already correct'
            self.result = 'no update required'

        return
    

    def set_note(self):
        """
        Sets a note to explain missing data
        """
        if self.cur_nick_site and not self.cur_nick_router:
            self.note += "site in cur nick, but that site has multiple routers in Nox (or no routers with valid name; less likely); "
        elif self.cur_nick_router and not self.cur_nick_site:
            self.note += "router in cur nick, but not site, and no router/site association found in Nox; "

        if self.location_site and not self.location_router:
            self.note += "lat/lon matched a site, but associated router name missing in Nox; "
        elif self.location_router and not self.location_site:
            self.note += "lat/lon matched a router, but associated site name missing in Nox; "

        self.note += "could not match Starlink device to a valid router"

        return


    def to_list(self):
        """
        Formats attributes as list, suitable for .csv row
        """
        return [self.cur_nick, self.sln, self.kit, self.adr,
                self.cur_nick_router, self.cur_nick_site,
                self.location_router, self.location_site,
                self.rec_nick, self.note, self.updated,
                self.name_src, self.router_src, self.result]

